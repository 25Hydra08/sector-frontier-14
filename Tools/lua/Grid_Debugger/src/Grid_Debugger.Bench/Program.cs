using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using Grid_Debugger.Core;

class Program
{
    static int Main(string[] args)
    {
        var file = Path.Combine(Path.GetTempPath(), "grid_debugger_bench.yml");
        int count = 10000;
        if (args.Length >= 1 && int.TryParse(args[0], out var c)) count = c;

        Console.WriteLine($"Generating YAML with {count} entities to {file}...");
        GenerateYaml(file, count);

        Console.WriteLine("Warm-up analyze...");
        var sw = Stopwatch.StartNew();
        var conflicts = YamlAnalyzer.AnalyzeFileForConflicts(file);
        sw.Stop();
        Console.WriteLine($"Analyze time: {sw.Elapsed.TotalSeconds:F2}s, conflicts: {conflicts.Count}");

        // Run baseline (simple) strategy
        Console.WriteLine("Running Orchestrator cleanup (simple)...");
        sw.Restart();
        var progress1 = new Progress<string>(s => { if ((s ?? string.Empty).Length > 0) Console.WriteLine(s); });
        var task1 = Orchestrator.RunCleanupAsync(file, Path.Combine(Path.GetTempPath(), "grid_debugger_bench_out_simple.yml"), progress1, System.Threading.CancellationToken.None, Orchestrator.Strategy.Simple);
        task1.Wait();
        sw.Stop();
        Console.WriteLine($"Orchestrator(simple) time: {sw.Elapsed.TotalSeconds:F2}s");

        // Run block strategy on fresh generated file
        Console.WriteLine("Running Orchestrator cleanup (block)...");
        sw.Restart();
        var progress2 = new Progress<string>(s => { if ((s ?? string.Empty).Length > 0) Console.WriteLine(s); });
        var task2 = Orchestrator.RunCleanupAsync(file, Path.Combine(Path.GetTempPath(), "grid_debugger_bench_out_block.yml"), progress2, System.Threading.CancellationToken.None, Orchestrator.Strategy.Block, 256);
        task2.Wait();
        sw.Stop();
        Console.WriteLine($"Orchestrator(block) time: {sw.Elapsed.TotalSeconds:F2}s");

        return 0;
    }

    static void GenerateYaml(string path, int count)
    {
        using var w = new StreamWriter(path, false, Encoding.UTF8);
        w.WriteLine("proto: BenchProto");
        w.WriteLine("entities:");
        for (int i = 0; i < count; i++)
        {
            w.WriteLine("- uid: " + (1000 + i));
            if (i % 50 == 0)
            {
                // introduce some conflict: missing components
                w.WriteLine("  name: bad_entity");
            }
            else
            {
                w.WriteLine("  components:");
                w.WriteLine("  - type: Transform");
                w.WriteLine("    pos: 0,0");
            }
        }
    }
}
