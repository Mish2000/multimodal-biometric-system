using System;
using System.Collections.Generic;

namespace ScannerCapture
{
    /// <summary>Finger positions 1-10 as in ANSI/NIST-ITL and SD302: right thumb to right little, then left.</summary>
    static class Fingers
    {
        static readonly string[] Names =
        {
            null, "right thumb", "right index", "right middle", "right ring", "right little",
            "left thumb", "left index", "left middle", "left ring", "left little",
        };

        public static string Name(int position) => Names[position];

        /// <summary>Parses "1-10", "2" or "2,3,7-9" into positions in the given order, without repeats.</summary>
        public static List<int> Parse(string spec)
        {
            var result = new List<int>();
            foreach (var part in spec.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var bounds = part.Trim().Split('-');
                if (bounds.Length > 2 || !int.TryParse(bounds[0], out int first) ||
                    !int.TryParse(bounds[bounds.Length - 1], out int last))
                {
                    throw new UsageException("Cannot read finger positions \"" + spec + "\"; use for example 1-10 or 2,7.");
                }
                int step = first <= last ? 1 : -1;
                for (int p = first; ; p += step)
                {
                    if (p < 1 || p > 10) throw new UsageException("Finger positions run from 1 to 10.");
                    if (!result.Contains(p)) result.Add(p);
                    if (p == last) break;
                }
            }
            if (result.Count == 0) throw new UsageException("No finger positions given.");
            return result;
        }
    }
}
