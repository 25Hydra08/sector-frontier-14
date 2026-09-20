using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using YamlDotNet.Core;
using YamlDotNet.Core.Events;

namespace Grid_Debugger.Validator
{
    class Program
    {
        static int Main(string[] args)
        {
            if (args.Length == 0)
            {
                Console.Error.WriteLine("Usage: Grid_Debugger.Validator --file <path>");
                return 2;
            }

            string? file = null;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--file" && i + 1 < args.Length)
                {
                    file = args[i + 1];
                    i++;
                }
            }

            if (file == null || !File.Exists(file))
            {
                Console.Error.WriteLine("File not found or not specified.");
                return 3;
            }

            try
            {
                var conflicts = Grid_Debugger.Core.YamlAnalyzer.AnalyzeFileForConflicts(file);
                var result = new
                {
                    success = conflicts.Count == 0,
                    conflicts = conflicts,
                    message = conflicts.Count == 0 ? "OK" : "Found conflicting entities"
                };

                Console.Out.WriteLine(JsonSerializer.Serialize(result));
                return 0;
            }
            catch (Exception ex)
            {
                var err = new { success = false, error = ex.Message };
                Console.Out.WriteLine(JsonSerializer.Serialize(err));
                return 1;
            }
        }

        // Analyzer moved to Grid_Debugger.Core.YamlAnalyzer
    }
}
