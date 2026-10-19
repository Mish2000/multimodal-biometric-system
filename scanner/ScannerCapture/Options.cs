using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace ScannerCapture
{
    /// <summary>A mistake in the command line; the usage text follows the message.</summary>
    sealed class UsageException : Exception
    {
        public UsageException(string message) : base(message) { }
    }

    /// <summary>"command --name value ... positional ..." command lines.</summary>
    sealed class Options
    {
        readonly Dictionary<string, string> _values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public string Command { get; private set; } = "help";
        public List<string> Positional { get; } = new List<string>();

        public static Options Parse(string[] args)
        {
            var options = new Options();
            if (args.Length == 0) return options;
            options.Command = args[0].ToLowerInvariant();
            for (int i = 1; i < args.Length; i++)
            {
                if (args[i].StartsWith("--", StringComparison.Ordinal))
                {
                    if (i + 1 >= args.Length) throw new UsageException("Option " + args[i] + " needs a value.");
                    options._values[args[i].Substring(2)] = args[++i];
                }
                else
                {
                    options.Positional.Add(args[i]);
                }
            }
            return options;
        }

        public void Allow(params string[] names)
        {
            var unknown = _values.Keys.Where(k => !names.Contains(k, StringComparer.OrdinalIgnoreCase)).ToList();
            if (unknown.Count > 0)
                throw new UsageException("Unknown option(s) for " + Command + ": --" + string.Join(", --", unknown));
        }

        public string Get(string name, string fallback) => _values.TryGetValue(name, out var v) ? v : fallback;

        public string Require(string name) =>
            _values.TryGetValue(name, out var v) ? v : throw new UsageException(Command + " needs --" + name + ".");

        public int GetInt(string name, int fallback, int min, int max)
        {
            if (!_values.TryGetValue(name, out var text)) return fallback;
            if (!int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out int value) || value < min || value > max)
                throw new UsageException("--" + name + " must be a whole number from " + min + " to " + max + ".");
            return value;
        }

        /// <summary>Reads "1000x1000".</summary>
        public void GetSize(string name, int fallbackWidth, int fallbackHeight, out int width, out int height)
        {
            width = fallbackWidth;
            height = fallbackHeight;
            if (!_values.TryGetValue(name, out var text)) return;
            var parts = text.ToLowerInvariant().Split('x');
            if (parts.Length != 2 || !int.TryParse(parts[0], out width) || !int.TryParse(parts[1], out height) ||
                width <= 0 || height <= 0)
                throw new UsageException("--" + name + " must look like 1000x1000.");
        }
    }
}
