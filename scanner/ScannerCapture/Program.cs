using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using NTwain;
using NTwain.Data;
using ScannerCapture.Imaging;
using ScannerCapture.Twain;

namespace ScannerCapture
{
    /// <summary>
    /// Scanner prototype (H7): captures native 1000 ppi fingerprints from the Biometrika HiScan PRO through
    /// TWAIN without the driver dialog, checks every capture and stores it as a lossless PNG with metadata.
    /// </summary>
    static class Program
    {
        const string Usage = @"ScannerCapture: native 1000 ppi captures from the HiScan PRO through TWAIN (H7).

Commands:
  probe          List TWAIN sources, describe the scanner's capabilities and try 1000 ppi;
                 every setting is returned to the driver's default at the end.
                 [--source NAME] [--resolution 1000] [--report local\scanner-probe.json]
                 [--scan-custom yes]  also ask the custom capability numbers 0x8000-0x81FF
  capture        Capture fingers one after another; each capture is checked and kept as
                 <out>\<session>\<session>_fNN_aN.png with a .json file next to it.
                 --session ID [--fingers 1-10] [--attempts 1] [--out captures]
                 [--resolution 1000] [--settle-ms 1500] [--timeout-s 30]
                 [--expect-size 1000x1000] [--settings FILE] [--source NAME]
  save-settings  Fallback: open the driver's own window once, choose 1000 ppi there, and save the
                 driver's settings (TWAIN custom DS data) for capture --settings.
                 --file local\NAME.dsdata [--source NAME] [--timeout-s 600]
  check          Run the capture checks on image files or folders (PNG, TIFF, BMP).
                 FILE_OR_FOLDER ... [--resolution 1000] [--expect-size 1000x1000]
  selftest       Check the image code on synthetic images; no scanner needed.

Fingers: 1 right thumb, 2 right index, 3 right middle, 4 right ring, 5 right little,
         6 left thumb, 7 left index, 8 left middle, 9 left ring, 10 left little.
Exit codes: 0 done, 1 usage or unexpected error, 2 scanner or fallback not available,
            3 a check failed or captures are missing.";

        [STAThread]
        static int Main(string[] args)
        {
            Console.OutputEncoding = Encoding.UTF8;
            try
            {
                var options = Options.Parse(args);
                switch (options.Command)
                {
                    case "probe": return TwainHost.Run(host => Probe(host, options));
                    case "capture": return TwainHost.Run(host => Capture(host, options));
                    case "save-settings": return TwainHost.Run(host => SaveSettings(host, options));
                    case "check": return Check(options);
                    case "selftest": return SelfTest.Run();
                    case "help":
                    case "--help":
                        Console.WriteLine(Usage);
                        return 0;
                    default:
                        throw new UsageException("Unknown command \"" + options.Command + "\".");
                }
            }
            catch (UsageException ex)
            {
                Console.Error.WriteLine(ex.Message);
                Console.Error.WriteLine();
                Console.Error.WriteLine(Usage);
                return 1;
            }
        }

        static int Probe(TwainHost host, Options options)
        {
            options.Allow("source", "resolution", "report", "scan-custom");
            int ppi = options.GetInt("resolution", 1000, 100, 4000);
            string reportPath = options.Get("report", Path.Combine("local", "scanner-probe.json"));
            var platform = PlatformInfo.Current;

            Console.WriteLine("Process: " + (Environment.Is64BitProcess ? "64" : "32") + "-bit. TWAIN manager: " +
                              platform.ExpectedDsmPath + (platform.UseNewWinDSM ? " (TWAIN 2)" : " (legacy twain_32)") + ".");
            var sources = host.Session.GetSources().ToList();
            Console.WriteLine("TWAIN sources (" + sources.Count + "):");
            foreach (var s in sources) Console.WriteLine("  " + s.Name + " | " + s.Manufacturer + " | " + s.ProductFamily + " | " + s.Version.Info + " | TWAIN " + s.ProtocolVersion);

            var report = new JsonObject
            {
                { "probed_utc", DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture) },
                { "tool", ToolInfo() },
                { "process_bits", Environment.Is64BitProcess ? 64 : 32 },
                { "twain_manager", Path.GetFileName(platform.ExpectedDsmPath) },
                { "sources", sources.Select(SourceInfo).ToList() },
            };

            string name = options.Get("source", Scanner.DefaultSourceName);
            int exitCode = 0;
            try
            {
                using (var scanner = Scanner.Open(host, name))
                {
                    var supported = scanner.SupportedCapabilities();
                    Console.WriteLine();
                    Console.WriteLine("Capabilities the source lists (" + supported.Count + "): " + string.Join(", ", supported));
                    Console.WriteLine();
                    Console.WriteLine("Capabilities this tool uses:");
                    var described = scanner.DescribeCapabilities();
                    foreach (var c in described) Console.WriteLine("  " + c.Key.PadRight(24) + c.Value);

                    Console.WriteLine();
                    Console.WriteLine("Every listed capability as the source reports it (read-only):");
                    var listed = new List<KeyValuePair<string, string>>();
                    foreach (var id in scanner.SupportedCapabilityIds())
                    {
                        var value = scanner.DescribeRaw(id) ?? "refused";
                        listed.Add(new KeyValuePair<string, string>(id + " (0x" + ((int)id).ToString("X4") + ")", value));
                        Console.WriteLine("  " + listed[listed.Count - 1].Key.PadRight(40) + value);
                    }
                    report.Add("listed_capabilities", Pairs(listed));

                    if (options.Get("scan-custom", "no") == "yes")
                    {
                        Console.WriteLine();
                        Console.WriteLine("Custom capabilities 0x8000-0x81FF that answer MSG_GET (read-only):");
                        var custom = new List<KeyValuePair<string, string>>();
                        for (int n = 0x8000; n <= 0x81FF; n++)
                        {
                            var value = scanner.DescribeRaw((CapabilityId)n);
                            if (value == null) continue;
                            custom.Add(new KeyValuePair<string, string>("0x" + n.ToString("X4"), value));
                            Console.WriteLine("  0x" + n.ToString("X4") + "  " + value);
                        }
                        if (custom.Count == 0) Console.WriteLine("  none");
                        report.Add("custom_capabilities", Pairs(custom));
                    }

                    Console.WriteLine();
                    Console.WriteLine("Negotiation for capture at " + ppi + " ppi:");
                    var steps = scanner.Configure(ppi);
                    foreach (var s in steps) Console.WriteLine("  " + s.Key.PadRight(24) + s.Value);
                    double x = scanner.CurrentResolution(true), y = scanner.CurrentResolution(false);
                    bool holds = Math.Abs(x - ppi) < 0.5 && Math.Abs(y - ppi) < 0.5;
                    Console.WriteLine();
                    bool settings = scanner.SupportsSettings();
                    Console.WriteLine(holds
                        ? "The source now holds " + ppi + " ppi. A capture will show whether the image really has it."
                        : "The source does not hold " + ppi + " ppi (it holds " + x + " x " + y + "). " + (settings
                            ? "Next: save-settings (the fallback)."
                            : "It keeps no settings either (CAP_CUSTOMDSDATA), so save-settings cannot help."));
                    report.Add("supports_settings", settings);

                    var resets = scanner.ResetConfigured();
                    Console.WriteLine("Settings returned to the driver's defaults: " +
                                      string.Join(", ", resets.Select(r => r.Key + " " + r.Value)) + ".");

                    report.Add("source", SourceInfo(scanner.Source));
                    report.Add("supported_capabilities", supported);
                    report.Add("capabilities", Pairs(described));
                    report.Add("negotiation", Pairs(steps));
                    report.Add("holds_requested_ppi", holds);
                    report.Add("reset_to_defaults", Pairs(resets));
                }
            }
            catch (ScannerException ex)
            {
                Console.WriteLine();
                Console.WriteLine(ex.Message);
                report.Add("error", ex.Message);
                exitCode = ex.ExitCode;
            }

            var folder = Path.GetDirectoryName(Path.GetFullPath(reportPath));
            Directory.CreateDirectory(folder);
            File.WriteAllText(reportPath, report.ToJson());
            Console.WriteLine();
            Console.WriteLine("Report: " + Path.GetFullPath(reportPath));
            return exitCode;
        }

        static int Capture(TwainHost host, Options options)
        {
            options.Allow("session", "fingers", "attempts", "out", "resolution", "settle-ms", "timeout-s", "expect-size", "settings", "source");
            string session = options.Require("session");
            if (!Regex.IsMatch(session, "^[A-Za-z0-9_-]{1,40}$"))
                throw new UsageException("--session may hold letters, digits, - and _ only.");
            var fingers = Fingers.Parse(options.Get("fingers", "1-10"));
            int attempts = options.GetInt("attempts", 1, 1, 20);
            int ppi = options.GetInt("resolution", 1000, 100, 4000);
            var settle = TimeSpan.FromMilliseconds(options.GetInt("settle-ms", 1500, 0, 10000));
            var timeout = TimeSpan.FromSeconds(options.GetInt("timeout-s", 30, 5, 600));
            options.GetSize("expect-size", 1000, 1000, out int width, out int height);
            string settingsFile = options.Get("settings", null);
            if (settingsFile != null && !File.Exists(settingsFile)) throw new UsageException("Settings file not found: " + settingsFile);
            string folder = Path.GetFullPath(Path.Combine(options.Get("out", "captures"), session));

            using (var scanner = Scanner.Open(host, options.Get("source", Scanner.DefaultSourceName)))
            {
                Console.WriteLine("Scanner: " + scanner.Source.Name + " (" + scanner.Source.Manufacturer + ", " + scanner.Source.Version.Info + ").");
                if (settingsFile != null)
                {
                    bool same = scanner.ApplySettings(File.ReadAllBytes(settingsFile));
                    Console.WriteLine("Driver settings applied from " + settingsFile +
                                      (same ? " (the source returns them unchanged)." : " (the source returns different bytes)."));
                }
                else
                {
                    foreach (var s in scanner.Configure(ppi)) Console.WriteLine("  " + s.Key.PadRight(24) + s.Value);
                }
                double heldX = scanner.CurrentResolution(true), heldY = scanner.CurrentResolution(false);
                Console.WriteLine("The source holds " + heldX + " x " + heldY + " ppi.");
                if (Math.Abs(heldX - ppi) >= 0.5 || Math.Abs(heldY - ppi) >= 0.5)
                    Console.WriteLine("Warning: that is not " + ppi + " ppi; the checks will show what the images really have.");

                Directory.CreateDirectory(folder);
                Console.WriteLine("Captures go to " + folder);
                Console.WriteLine();

                bool quit = false, complete = true;
                var summary = new List<string>();
                foreach (int finger in fingers)
                {
                    int firstAttempt = NextAttempt(folder, session, finger);
                    int kept = 0, rejected = 0;
                    while (kept < attempts)
                    {
                        Console.Write("[f" + finger.ToString("00") + " " + Fingers.Name(finger) + ", capture " + (kept + 1) + " of " + attempts +
                                      "] Place the finger and press Enter (s = skip finger, q = quit): ");
                        string answer = (Console.ReadLine() ?? "q").Trim().ToLowerInvariant();
                        if (answer == "q") { quit = true; break; }
                        if (answer == "s") break;

                        int attempt = firstAttempt + kept;
                        if (CaptureOne(scanner, session, finger, attempt, folder, ppi, width, height, settle, timeout, settingsFile)) kept++;
                        else rejected++;
                    }
                    if (kept < attempts) complete = false;
                    summary.Add("  f" + finger.ToString("00") + " " + Fingers.Name(finger).PadRight(13) + kept + " kept" +
                                (rejected > 0 ? ", " + rejected + " not kept" : ""));
                    if (quit) break;
                }
                if (quit && summary.Count < fingers.Count) complete = false;

                Console.WriteLine();
                Console.WriteLine("Summary:");
                foreach (var line in summary) Console.WriteLine(line);
                return complete ? 0 : 3;
            }
        }

        /// <summary>One capture: transfer, decode, check, then keep it or file it under rejected\.</summary>
        static bool CaptureOne(Scanner scanner, string session, int finger, int attempt, string folder, int ppi,
            int width, int height, TimeSpan settle, TimeSpan timeout, string settingsFile)
        {
            var captured = DateTime.UtcNow;
            var outcome = scanner.Capture(settle, timeout);
            if (outcome.Error != null)
            {
                Console.WriteLine("  Capture failed: " + outcome.Error);
                return false;
            }

            GrayImage image;
            BmpInfo bmp;
            try
            {
                image = Bmp.DecodeGray(outcome.Bmp, out bmp);
            }
            catch (InvalidDataException ex)
            {
                Console.WriteLine("  The image cannot be stored without loss: " + ex.Message);
                return false;
            }

            var info = outcome.ImageInfo;
            double reportedX = info != null ? info.XResolution : double.NaN;
            double reportedY = info != null ? info.YResolution : double.NaN;
            var checks = CaptureChecks.Run(image, width, height, ppi, reportedX, reportedY, out var detail);
            bool passed = CaptureChecks.AllPassed(checks);

            string name = session + "_f" + finger.ToString("00") + "_a" + attempt;
            string target = folder;
            if (!passed)
            {
                target = Path.Combine(folder, "rejected");
                name += "_" + captured.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture);
                Directory.CreateDirectory(target);
            }
            double pngPpi = reportedX > 0 && !double.IsNaN(reportedX) ? reportedX : ppi;
            string pngPath = Path.Combine(target, name + ".png");
            ImageFiles.SavePng(image, pngPpi, pngPath);

            var metadata = new JsonObject
            {
                { "file", name + ".png" },
                { "sha256", Sha256(pngPath) },
                { "kept", passed },
                { "session", session },
                { "finger_position", finger },
                { "finger", Fingers.Name(finger) },
                { "attempt", attempt },
                { "captured_utc", captured.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture) },
                { "width", image.Width },
                { "height", image.Height },
                { "png_ppi", pngPpi },
                { "requested_ppi", ppi },
                { "driver_settings_file", settingsFile == null ? null : Path.GetFileName(settingsFile) },
                { "source", SourceInfo(scanner.Source) },
                { "image_info", info == null ? null : new JsonObject
                    {
                        { "x_resolution", info.XResolution },
                        { "y_resolution", info.YResolution },
                        { "image_width", info.ImageWidth },
                        { "image_length", info.ImageLength },
                        { "bits_per_pixel", (int)info.BitsPerPixel },
                        { "pixel_type", info.PixelType.ToString() },
                        { "compression", info.Compression.ToString() },
                    } },
                { "bmp", new JsonObject
                    {
                        { "bits_per_pixel", bmp.BitsPerPixel },
                        { "top_down", bmp.TopDown },
                        { "ppi_x", Math.Round(bmp.DpiX, 2) },
                        { "ppi_y", Math.Round(bmp.DpiY, 2) },
                        { "palette_entries", bmp.PaletteEntries },
                        { "identity_palette", bmp.IdentityPalette },
                    } },
                { "timing_ms", new JsonObject
                    {
                        { "transfer_ready_after", outcome.TransferReadyAfterMs },
                        { "settle_wait", outcome.SettleWaitMs },
                        { "total", outcome.TotalMs },
                    } },
                { "checks", checks.Select(c => new JsonObject { { "name", c.Name }, { "passed", c.Passed }, { "detail", c.Detail } }).ToList() },
                { "fine_detail", detail == null ? null : new JsonObject
                    {
                        { "share", detail.Share },
                        { "share_after_round_trip", detail.ShareAfterRoundTrip },
                        { "kept", detail.Kept },
                        { "replicated", detail.Replicated },
                        { "crop_std", detail.CropStd },
                    } },
                { "tool", ToolInfo() },
            };
            File.WriteAllText(Path.Combine(target, name + ".json"), metadata.ToJson());

            Console.WriteLine("  " + (passed ? "Kept " : "Not kept, filed under rejected\\: ") + name + ".png (" + outcome.TotalMs + " ms)");
            foreach (var c in checks) Console.WriteLine("    " + (c.Passed ? "ok    " : "FAILED") + " " + c.Name + ": " + c.Detail);
            return passed;
        }

        static int SaveSettings(TwainHost host, Options options)
        {
            options.Allow("file", "source", "timeout-s");
            string file = options.Require("file");
            if (File.Exists(file)) throw new UsageException(file + " already exists; choose another name.");
            var timeout = TimeSpan.FromSeconds(options.GetInt("timeout-s", 600, 10, 3600));

            using (var scanner = Scanner.Open(host, options.Get("source", Scanner.DefaultSourceName)))
            {
                if (!scanner.SupportsSettings())
                {
                    Console.WriteLine("The source does not support saved settings (CAP_CUSTOMDSDATA), so this fallback is not available.");
                    return 2;
                }
                Console.WriteLine("The driver's window opens now. Choose 1000 ppi there; if it offers to scan, scan one finger;");
                Console.WriteLine("then close the window with OK. The tool keeps the driver's settings, not the image.");
                var outcome = scanner.ShowDriverDialog(timeout);
                if (outcome.Bmp != null)
                {
                    try
                    {
                        var image = Bmp.DecodeGray(outcome.Bmp, out _);
                        var info = outcome.ImageInfo;
                        var checks = CaptureChecks.Run(image, 1000, 1000, 1000,
                            info != null ? info.XResolution : double.NaN, info != null ? info.YResolution : double.NaN, out _);
                        Console.WriteLine("Image scanned from the window (not saved):");
                        foreach (var c in checks) Console.WriteLine("  " + (c.Passed ? "ok    " : "FAILED") + " " + c.Name + ": " + c.Detail);
                    }
                    catch (InvalidDataException ex)
                    {
                        Console.WriteLine("The scanned image could not be read: " + ex.Message);
                    }
                }
                else
                {
                    Console.WriteLine("No image was scanned from the window.");
                }

                var settings = scanner.ReadSettings();
                if (settings == null || settings.Length == 0)
                {
                    Console.WriteLine("The source returns no settings (TWAIN custom DS data), so this fallback is not available.");
                    return 2;
                }
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(file)));
                File.WriteAllBytes(file, settings);
                Console.WriteLine("Saved " + settings.Length + " bytes of driver settings to " + file + ".");
                Console.WriteLine("Use them with: capture --settings " + file + " ...");
                return 0;
            }
        }

        static int Check(Options options)
        {
            options.Allow("resolution", "expect-size");
            int ppi = options.GetInt("resolution", 1000, 100, 4000);
            options.GetSize("expect-size", 1000, 1000, out int width, out int height);
            var files = new List<string>();
            foreach (var arg in options.Positional)
            {
                if (Directory.Exists(arg))
                {
                    files.AddRange(Directory.GetFiles(arg)
                        .Where(f => new[] { ".png", ".tif", ".tiff", ".bmp" }.Contains(Path.GetExtension(f).ToLowerInvariant()))
                        .OrderBy(f => f, StringComparer.Ordinal));
                }
                else if (File.Exists(arg))
                {
                    files.Add(arg);
                }
                else
                {
                    throw new UsageException("Not found: " + arg);
                }
            }
            if (files.Count == 0) throw new UsageException("check needs image files or folders.");

            bool all = true;
            foreach (var file in files)
            {
                var image = ImageFiles.Load(file, out double dpiX, out double dpiY, out string format);
                var checks = CaptureChecks.Run(image, width, height, ppi, dpiX, dpiY, out var d);
                bool passed = CaptureChecks.AllPassed(checks);
                all &= passed;
                Console.WriteLine(Path.GetFileName(file) + ": " + (passed ? "ok" : "FAILED " + string.Join(", ", checks.Where(c => !c.Passed).Select(c => c.Name))) +
                    " | " + format + " " + image.Width + "x" + image.Height + " " + dpiX.ToString("0.##", CultureInfo.InvariantCulture) + " ppi" +
                    (d == null ? "" : " | share " + d.Share.ToString("0.00000", CultureInfo.InvariantCulture) +
                        " after " + d.ShareAfterRoundTrip.ToString("0.00000", CultureInfo.InvariantCulture) +
                        " kept " + d.Kept.ToString("0.000", CultureInfo.InvariantCulture) +
                        " replicated " + d.Replicated.ToString("0.000", CultureInfo.InvariantCulture) +
                        " spread " + d.CropStd.ToString("0.0", CultureInfo.InvariantCulture)));
            }
            return all ? 0 : 3;
        }

        /// <summary>The first free attempt number for a finger, so earlier captures are never overwritten.</summary>
        static int NextAttempt(string folder, string session, int finger)
        {
            var pattern = new Regex("^" + Regex.Escape(session) + "_f" + finger.ToString("00") + "_a(\\d+)\\.png$", RegexOptions.IgnoreCase);
            int max = 0;
            if (Directory.Exists(folder))
            {
                foreach (var f in Directory.GetFiles(folder, "*.png"))
                {
                    var m = pattern.Match(Path.GetFileName(f));
                    if (m.Success) max = Math.Max(max, int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture));
                }
            }
            return max + 1;
        }

        static string Sha256(string path)
        {
            using (var sha = SHA256.Create())
            using (var stream = File.OpenRead(path))
            {
                return string.Concat(sha.ComputeHash(stream).Select(b => b.ToString("x2")));
            }
        }

        static JsonObject SourceInfo(DataSource source) => new JsonObject
        {
            { "name", source.Name },
            { "manufacturer", source.Manufacturer },
            { "product_family", source.ProductFamily },
            { "version", source.Version.Info },
            { "twain_protocol", source.ProtocolVersion?.ToString() },
        };

        static JsonObject ToolInfo() => new JsonObject
        {
            { "name", "ScannerCapture" },
            { "version", typeof(Program).Assembly.GetName().Version.ToString(3) },
            { "ntwain", FileVersionInfo.GetVersionInfo(typeof(TwainSession).Assembly.Location).ProductVersion },
        };

        static List<JsonObject> Pairs(IEnumerable<KeyValuePair<string, string>> pairs) =>
            pairs.Select(p => new JsonObject { { "name", p.Key }, { "value", p.Value } }).ToList();
    }
}
