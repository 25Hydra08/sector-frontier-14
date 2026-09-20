using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace Grid_Debugger.Core
{
    public static class Orchestrator
    {
        public static async Task<(bool success, string message)> RunCleanupAsync(string inputFile, string outputFile, IProgress<string>? progress = null, CancellationToken ct = default)
        {
            progress?.Report("Создание временной копии... ");
            var tempDir = Path.Combine(Path.GetTempPath(), "Grid_Debugger", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(tempDir);
            var working = Path.Combine(tempDir, Path.GetFileName(inputFile));
            File.Copy(inputFile, working, true);

            try
            {
                while (true)
                {
                    ct.ThrowIfCancellationRequested();
                    progress?.Report("Анализ маппинга на конфликты...");
                    var conflicts = YamlAnalyzer.AnalyzeFileForConflicts(working);
                    if (conflicts.Count == 0)
                    {
                        progress?.Report("Конфликтов не найдено. Сохранение результата...");
                        Directory.CreateDirectory(Path.GetDirectoryName(outputFile) ?? Environment.CurrentDirectory);
                        File.Copy(working, outputFile, true);
                        return (true, "Готово");
                    }

                    progress?.Report($"Найдено {conflicts.Count} конфликтных сущностей.");
                    var next = Path.Combine(tempDir, Guid.NewGuid().ToString("N") + ".yml");

                    progress?.Report("Удаляю по списку uid (simple)...");
                    var set = new HashSet<long>(conflicts);
                    var removed = EntityRemover.RemoveEntitiesByUids(working, next, set);
                    foreach (var (proto, uid) in removed)
                        progress?.Report($"proto: {proto ?? "<unknown>"} uid: {uid}");
                    File.Delete(working);
                    working = next;
                }
            }
            finally
            {
                try { Directory.Delete(tempDir, true); } catch { }
            }
        }
    }
}
