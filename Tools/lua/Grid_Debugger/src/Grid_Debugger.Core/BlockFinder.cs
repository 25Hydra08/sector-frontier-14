using System;
using System.Collections.Generic;
using System.Threading.Tasks;

namespace Grid_Debugger.Core
{
    // BlockFinder removed: no longer used. Keep file for reference but simplify to minimal stub.
    public static class BlockFinder
    {
        public delegate System.Threading.Tasks.Task<bool> BlockTestAsync(int startInclusive, int endExclusive);

        public static System.Threading.Tasks.Task<System.Collections.Generic.List<(int start, int end)>> FindConflictingIndicesAsync(int count, int initialBlockSize, BlockTestAsync tester, int minBlockSize = 1)
        {
            return System.Threading.Tasks.Task.FromResult(new System.Collections.Generic.List<(int start, int end)>());
        }
    }
}
