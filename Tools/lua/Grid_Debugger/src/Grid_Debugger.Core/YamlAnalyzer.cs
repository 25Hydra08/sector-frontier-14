using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using YamlDotNet.Core;
using YamlDotNet.Core.Events;

namespace Grid_Debugger.Core
{
    public static class YamlAnalyzer
    {
        // Анализирует YAML-файл и возвращает список конфликтных uid.
        // Критерии конфликтов: нет поля 'components' или 'Transform' без 'pos'.
        public static List<long> AnalyzeFileForConflicts(string path)
        {
            var conflicts = new List<long>();

            using var reader = new StreamReader(path);
            var parser = new Parser(reader);
            if (!parser.MoveNext())
                return conflicts;

            // Ищем ключ 'entities'
            while (parser.Current != null)
            {
                if (parser.Current is Scalar s && s.Value == "entities")
                {
                    parser.MoveNext();
                    break;
                }

                parser.MoveNext();
            }

            if (parser.Current == null)
                return conflicts;

            if (!(parser.Current is SequenceStart))
                return conflicts;

            parser.MoveNext();

            while (!(parser.Current is SequenceEnd))
            {
                // Буферизуем один элемент
                var buffer = new List<ParsingEvent>();
                int depth = 0;
                do
                {
                    var ev = parser.Current ?? throw new InvalidOperationException("Unexpected EOF while parsing entity");
                    buffer.Add(ev);
                    if (ev is MappingStart || ev is SequenceStart) depth++;
                    else if (ev is MappingEnd || ev is SequenceEnd) depth--;
                    parser.MoveNext();
                }
                while (depth > 0 && parser.Current != null);

                long? uid = null;
                bool hasComponents = false;
                bool transformHasPos = true; // assume true until proven otherwise

                for (int i = 0; i < buffer.Count; i++)
                {
                    if (buffer[i] is Scalar key && key.Value == "uid")
                    {
                        if (i + 1 < buffer.Count && buffer[i + 1] is Scalar val)
                            if (long.TryParse(val.Value, out var parsed)) uid = parsed;
                    }

                    if (buffer[i] is Scalar k2 && k2.Value == "components")
                    {
                        hasComponents = true;
                    }

                    if (buffer[i] is Scalar k3 && k3.Value == "type")
                    {
                        if (i + 1 < buffer.Count && buffer[i + 1] is Scalar typeVal && typeVal.Value == "Transform")
                        {
                            bool posFound = false;
                            for (int j = i; j < Math.Min(buffer.Count, i + 60); j++)
                            {
                                if (buffer[j] is Scalar s2 && s2.Value == "pos") { posFound = true; break; }
                            }
                            if (!posFound) transformHasPos = false;
                        }
                    }
                }

                if (!hasComponents || !transformHasPos)
                {
                    if (uid.HasValue)
                        conflicts.Add(uid.Value);
                }
            }

            return conflicts.Distinct().ToList();
        }

        // Быстро подсчитать количество сущностей в секции 'entities' без детального буферинга
        public static int CountEntities(string path)
        {
            using var reader = new StreamReader(path);
            var parser = new Parser(reader);
            if (!parser.MoveNext())
                return 0;

            while (parser.Current != null)
            {
                if (parser.Current is Scalar s && s.Value == "entities")
                {
                    parser.MoveNext();
                    break;
                }
                parser.MoveNext();
            }

            if (parser.Current == null || !(parser.Current is SequenceStart))
                return 0;

            int count = 0;
            parser.MoveNext();
            while (!(parser.Current is SequenceEnd))
            {
                int depth = 0;
                do
                {
                    var ev = parser.Current ?? throw new InvalidOperationException("Unexpected EOF while counting entities");
                    if (ev is MappingStart || ev is SequenceStart) depth++;
                    else if (ev is MappingEnd || ev is SequenceEnd) depth--;
                    parser.MoveNext();
                }
                while (depth > 0 && parser.Current != null);

                count++;
            }

            return count;
        }

        // Проверяет наличие конфликтов в диапазоне индексов [startInclusive, endExclusive).
        // Возвращает true при первом найденном конфликте внутри диапазона.
        public static bool HasConflictsInRange(string path, int startInclusive, int endExclusive)
        {
            if (startInclusive >= endExclusive) return false;

            using var reader = new StreamReader(path);
            var parser = new Parser(reader);
            if (!parser.MoveNext())
                return false;

            // Найти entities
            while (parser.Current != null)
            {
                if (parser.Current is Scalar s && s.Value == "entities")
                {
                    parser.MoveNext();
                    break;
                }
                parser.MoveNext();
            }

            if (parser.Current == null || !(parser.Current is SequenceStart))
                return false;

            int idx = 0;
            parser.MoveNext();
            while (!(parser.Current is SequenceEnd))
            {
                // Буферизуем один элемент
                var buffer = new List<ParsingEvent>();
                int depth = 0;
                do
                {
                    var ev = parser.Current ?? throw new InvalidOperationException("Unexpected EOF while parsing entity");
                    buffer.Add(ev);
                    if (ev is MappingStart || ev is SequenceStart) depth++;
                    else if (ev is MappingEnd || ev is SequenceEnd) depth--;
                    parser.MoveNext();
                }
                while (depth > 0 && parser.Current != null);

                if (idx >= startInclusive && idx < endExclusive)
                {
                    long? uid = null;
                    bool hasComponents = false;
                    bool transformHasPos = true;

                    for (int i = 0; i < buffer.Count; i++)
                    {
                        if (buffer[i] is Scalar key && key.Value == "uid")
                        {
                            if (i + 1 < buffer.Count && buffer[i + 1] is Scalar val)
                                if (long.TryParse(val.Value, out var parsed)) uid = parsed;
                        }

                        if (buffer[i] is Scalar k2 && k2.Value == "components")
                        {
                            hasComponents = true;
                        }

                        if (buffer[i] is Scalar k3 && k3.Value == "type")
                        {
                            if (i + 1 < buffer.Count && buffer[i + 1] is Scalar typeVal && typeVal.Value == "Transform")
                            {
                                bool posFound = false;
                                for (int j = i; j < Math.Min(buffer.Count, i + 60); j++)
                                {
                                    if (buffer[j] is Scalar s2 && s2.Value == "pos") { posFound = true; break; }
                                }
                                if (!posFound) transformHasPos = false;
                            }
                        }
                    }

                    if (!hasComponents || !transformHasPos)
                    {
                        if (uid.HasValue) return true;
                    }
                }

                idx++;
            }

            return false;
        }
    }
}
