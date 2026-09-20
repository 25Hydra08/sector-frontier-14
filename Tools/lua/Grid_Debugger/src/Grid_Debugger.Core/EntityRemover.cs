using System;
using System.Collections.Generic;
using System.IO;
using YamlDotNet.Core;
using YamlDotNet.Core.Events;

namespace Grid_Debugger.Core
{
    public static class EntityRemover
    {
        // Удаляет сущности по множеству uid. Реализовано потоково: читаем события YAML и буферизуем
        // только текущую сущность для принятия решения удалить или вывести.
        // Возвращает список удалённых сущностей как пары (proto, uid)
        public static List<(string? proto, long uid)> RemoveEntitiesByUids(string inputPath, string outputPath, ISet<long> removeUids)
        {
            using var reader = new StreamReader(inputPath);
            var parser = new Parser(reader);
            using var writer = new StreamWriter(outputPath, false);
            var emitter = new Emitter(writer);

            // Инициализируем парсер
            if (!parser.MoveNext())
                return new List<(string? proto, long uid)>();

            // Копируем события, пока не найдём ключ 'entities'
            string? lastSeenProto = null;
            while (parser.Current != null)
            {
                var current = parser.Current!;
                if (current is Scalar s && s.Value == "entities")
                {
                    emitter.Emit(current); // emit key
                    parser.MoveNext();
                    break;
                }

                // capture proto if present before entities sequence
                if (current is Scalar s2 && s2.Value == "proto")
                {
                    // move to next to read proto value if possible
                    parser.MoveNext();
                    if (parser.Current is Scalar protoVal)
                    {
                        lastSeenProto = protoVal.Value;
                        emitter.Emit(s2);
                        emitter.Emit(protoVal);
                        parser.MoveNext();
                        continue;
                    }
                }

                emitter.Emit(current);
                parser.MoveNext();
            }

            if (parser.Current == null)
            {
                // EOF — ничего больше
                writer.Flush();
                return new List<(string? proto, long uid)>();
            }

            // Ожидаем SequenceStart
            if (!(parser.Current is SequenceStart))
                throw new InvalidOperationException("Ожидается sequence для entities");

            emitter.Emit(parser.Current); // SequenceStart
            parser.MoveNext();

            int idx = 0;
            // Проходим по элементам последовательности
            var removed = new List<(string? proto, long uid)>();
            while (!(parser.Current is SequenceEnd))
            {
                // Буферизуем события текущего элемента (mapping/sequence)
                var buffer = new List<ParsingEvent>();
                int depth = 0;

                // Если текущий эвент - MappingStart или SequenceStart, учтём его
                do
                {
                    var ev = parser.Current ?? throw new InvalidOperationException("Unexpected EOF while reading entity");
                    buffer.Add(ev);

                    if (ev is MappingStart || ev is SequenceStart) depth++;
                    else if (ev is MappingEnd || ev is SequenceEnd) depth--;

                    parser.MoveNext();
                }
                while (depth > 0 && parser.Current != null);

                // В buffer содержатся все события элемента
                long? foundUid = null;
                string? foundProto = null;
                for (int i = 0; i < buffer.Count; i++)
                {
                    if (buffer[i] is Scalar key && key.Value == "uid")
                    {
                        // следующая скалярная — значение
                        if (i + 1 < buffer.Count && buffer[i + 1] is Scalar val)
                        {
                            if (long.TryParse(val.Value, out var parsed))
                                foundUid = parsed;
                        }
                    }
                    // также ищем proto внутри элемента
                    if (buffer[i] is Scalar pkey && pkey.Value == "proto")
                    {
                        if (i + 1 < buffer.Count && buffer[i + 1] is Scalar pval)
                            foundProto = pval.Value;
                    }
                }

                bool shouldRemove = false;
                if (foundUid.HasValue && removeUids.Contains(foundUid.Value))
                    shouldRemove = true;

                if (!shouldRemove)
                {
                    // Выводим buffered events
                    foreach (var ev in buffer)
                        emitter.Emit(ev);
                }
                else
                {
                    // determine proto: prefer foundProto, else use lastSeenProto
                    var protoToReport = foundProto ?? lastSeenProto;
                    removed.Add((protoToReport, foundUid!.Value));
                }

                idx++;
            }

            // SequenceEnd
            emitter.Emit(parser.Current);
            parser.MoveNext();

            // Копируем оставшиеся события
            while (parser.Current != null)
            {
                emitter.Emit(parser.Current);
                parser.MoveNext();
            }

            writer.Flush();
            return removed;
        }

        // Удаляет сущности по списку индексных диапазонов [startInclusive, endExclusive).
        // Диапазоны должны быть не пересекающимися и будут сортированы в методе.
        // Возвращает список удалённых сущностей как пары (proto, uid).
        public static List<(string? proto, long uid)> RemoveEntitiesByIndexRanges(string inputPath, string outputPath, List<(int start, int end)> ranges)
        {
            if (ranges == null) throw new ArgumentNullException(nameof(ranges));

            // нормализуем и сортируем диапазоны
            ranges.Sort((a, b) => a.start.CompareTo(b.start));

            using var reader = new StreamReader(inputPath);
            var parser = new Parser(reader);
            using var writer = new StreamWriter(outputPath, false);
            var emitter = new Emitter(writer);

            if (!parser.MoveNext())
                return new List<(string? proto, long uid)>();

            string? lastSeenProto = null;
            while (parser.Current != null)
            {
                var current = parser.Current!;
                if (current is Scalar s && s.Value == "entities")
                {
                    emitter.Emit(current);
                    parser.MoveNext();
                    break;
                }

                if (current is Scalar s2 && s2.Value == "proto")
                {
                    parser.MoveNext();
                    if (parser.Current is Scalar protoVal)
                    {
                        lastSeenProto = protoVal.Value;
                        emitter.Emit(s2);
                        emitter.Emit(protoVal);
                        parser.MoveNext();
                        continue;
                    }
                }

                emitter.Emit(current);
                parser.MoveNext();
            }

            if (parser.Current == null)
            {
                writer.Flush();
                return new List<(string? proto, long uid)>();
            }

            if (!(parser.Current is SequenceStart))
                throw new InvalidOperationException("Ожидается sequence для entities");

            emitter.Emit(parser.Current);
            parser.MoveNext();

            int idx = 0;
            int rangeIndex = 0;
            var removed = new List<(string? proto, long uid)>();

            while (!(parser.Current is SequenceEnd))
            {
                // Продвигаем rangeIndex при необходимости
                while (rangeIndex < ranges.Count && idx >= ranges[rangeIndex].end) rangeIndex++;
                bool inRange = rangeIndex < ranges.Count && idx >= ranges[rangeIndex].start && idx < ranges[rangeIndex].end;

                var buffer = inRange ? null : new List<ParsingEvent>();

                int depth = 0;
                long? foundUid = null;
                string? foundProto = null;

                bool nextUidValue = false;
                bool nextProtoValue = false;

                // Читаем события текущего элемента
                do
                {
                    var ev = parser.Current ?? throw new InvalidOperationException("Unexpected EOF while reading entity");
                    if (buffer != null) buffer.Add(ev);

                    if (ev is Scalar sc)
                    {
                        if (nextUidValue)
                        {
                            if (long.TryParse(sc.Value, out var v)) foundUid = v;
                            nextUidValue = false;
                        }
                        else if (nextProtoValue)
                        {
                            foundProto = sc.Value;
                            nextProtoValue = false;
                        }
                        else if (sc.Value == "uid")
                        {
                            nextUidValue = true;
                        }
                        else if (sc.Value == "proto")
                        {
                            nextProtoValue = true;
                        }
                    }

                    if (ev is MappingStart || ev is SequenceStart) depth++;
                    else if (ev is MappingEnd || ev is SequenceEnd) depth--;

                    parser.MoveNext();
                }
                while (depth > 0 && parser.Current != null);

                if (!inRange)
                {
                    // Выводим буфер
                    foreach (var ev in buffer!) emitter.Emit(ev);
                }
                else
                {
                    var protoToReport = foundProto ?? lastSeenProto;
                    if (foundUid.HasValue)
                        removed.Add((protoToReport, foundUid.Value));
                }

                idx++;
            }

            // SequenceEnd
            emitter.Emit(parser.Current);
            parser.MoveNext();

            while (parser.Current != null)
            {
                emitter.Emit(parser.Current);
                parser.MoveNext();
            }

            writer.Flush();
            return removed;
        }
    }
}
