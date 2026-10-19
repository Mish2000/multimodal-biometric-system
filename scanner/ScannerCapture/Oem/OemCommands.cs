using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using ScannerCapture.Imaging;

namespace ScannerCapture.Oem
{
    /// <summary>H8: automatic capture outside TWAIN. The parent bounds a hung native call with a worker process.</summary>
    static class OemCommands
    {
        public static int RunIsolated(string[] args)
        {
            var options = Options.Parse(args);
            int seconds = options.GetInt("timeout-s", 60, 5, 600);
            return RunWorkerProcess(new[] { "_" + args[0].ToLowerInvariant() }.Concat(args.Skip(1)), seconds);
        }

        /// <summary>
        /// H9: guided capture of separate placements. The parent asks for each finger and placement and runs the
        /// unchanged H8 worker for one accepted image per placement, so time spent answering never counts against
        /// the worker's deadline. An interrupted session resumes after the highest kept placement of each finger.
        /// </summary>
        public static int RunGuided(string[] args)
        {
            var options = Options.Parse(args);
            options.Allow("driver-dir", "session", "fingers", "placements", "timeout-s", "settle-ms", "out");
            string directory = options.Require("driver-dir"), session = options.Require("session");
            if (!Regex.IsMatch(session, "^[A-Za-z0-9_-]{1,40}$")) throw new UsageException("--session may hold letters, digits, - and _ only.");
            var fingers = Fingers.Parse(options.Get("fingers", "1-10"));
            int placements = options.GetInt("placements", 3, 1, 10);
            int seconds = options.GetInt("timeout-s", 30, 5, 600);
            int settle = options.GetInt("settle-ms", 1500, 0, 10000);
            string output = options.Get("out", "captures");
            string folder = UnderRoot(Path.Combine(output, session), "captures");

            Console.WriteLine("Guided native capture (H9): session " + session + ", " + placements + " separate placements per finger.");
            Console.WriteLine("Lift the finger off the glass between placements: frames of one placement are not separate impressions.");
            bool quit = false, complete = true;
            var summary = new List<string>();
            foreach (int finger in fingers)
            {
                int placement = KeptPlacements(folder, session, finger) + 1;
                while (!quit && placement <= placements)
                {
                    Console.WriteLine();
                    Console.Write("[f" + finger.ToString("00") + " " + Fingers.Name(finger) + ", placement " + placement + " of " + placements +
                                  "] Place the finger, then press Enter (s = skip finger, q = quit): ");
                    string answer = (Console.ReadLine() ?? "q").Trim().ToLowerInvariant();
                    if (answer == "q") { quit = true; break; }
                    if (answer == "s") break;
                    int code = RunWorkerProcess(new[] {
                        "_oem-capture", "--driver-dir", directory, "--session", session, "--out", output,
                        "--finger", finger.ToString(CultureInfo.InvariantCulture), "--placement", placement.ToString(CultureInfo.InvariantCulture),
                        "--attempts", "1", "--timeout-s", seconds.ToString(CultureInfo.InvariantCulture), "--settle-ms", settle.ToString(CultureInfo.InvariantCulture) }, seconds);
                    if (code == 0) { Console.WriteLine("Placement " + placement + " kept. Lift the finger off the glass."); placement++; }
                    else Console.WriteLine("No image was kept for this placement; it will be asked again.");
                }
                int kept = KeptPlacements(folder, session, finger);
                if (kept < placements) complete = false;
                summary.Add("  f" + finger.ToString("00") + " " + Fingers.Name(finger).PadRight(13) + Math.Min(kept, placements) + " of " + placements + " placements kept");
                if (quit) break;
            }
            if (summary.Count < fingers.Count) complete = false;
            Console.WriteLine();
            Console.WriteLine("Summary (" + folder + "):");
            foreach (var line in summary) Console.WriteLine(line);
            return complete ? 0 : 3;
        }

        /// <summary>H9: the highest placement already kept for a finger; rejected frames are not counted.</summary>
        internal static int KeptPlacements(string folder, string session, int finger)
        {
            if (!Directory.Exists(folder)) return 0;
            var pattern = new Regex("^" + Regex.Escape(session) + "_f" + finger.ToString("00") + "_p(\\d+)_.*\\.png$", RegexOptions.IgnoreCase);
            int highest = 0;
            foreach (var file in Directory.GetFiles(folder, "*.png"))
            {
                var match = pattern.Match(Path.GetFileName(file));
                if (match.Success) highest = Math.Max(highest, int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture));
            }
            return highest;
        }

        static int RunWorkerProcess(IEnumerable<string> workerArgs, int seconds)
        {
            var start = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location, string.Join(" ", workerArgs.Select(Quote)))
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                WorkingDirectory = Environment.CurrentDirectory,
            };
            using (var process = new Process { StartInfo = start })
            {
                process.OutputDataReceived += (sender, e) => { if (e.Data != null) Console.WriteLine(e.Data); };
                process.ErrorDataReceived += (sender, e) => { if (e.Data != null) Console.Error.WriteLine(e.Data); };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                if (!process.WaitForExit((seconds + 15) * 1000))
                {
                    process.Kill();
                    process.WaitForExit();
                    Console.Error.WriteLine("The OEM worker exceeded its deadline and was stopped. No capture is claimed as successful.");
                    return 2;
                }
                process.WaitForExit(); // drain asynchronous output
                return process.ExitCode;
            }
        }

        // H8: preserve arbitrary Windows paths/arguments when starting the isolated worker.
        internal static string Quote(string value)
        {
            var result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value)
            {
                if (c == '\\') { slashes++; continue; }
                result.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
                result.Append(c);
                slashes = 0;
            }
            return result.Append('\\', slashes * 2).Append('"').ToString();
        }

        public static int RunWorker(Options options)
        {
            try
            {
                using (var mutex = new Mutex(false, @"Local\MultimodalBiometricSystem.HiScan.H8"))
                {
                    bool acquired;
                    try { acquired = mutex.WaitOne(0); }
                    catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) throw new IOException("Another native scanner command is running.");
                    try { return options.Command == "_oem-probe" ? Probe(options) : Capture(options); }
                    finally { mutex.ReleaseMutex(); }
                }
            }
            catch (UsageException) { throw; }
            catch (Exception ex) { Console.Error.WriteLine(ex.Message); return 2; }
        }

        static int Probe(Options options)
        {
            options.Allow("driver-dir", "report", "timeout-s");
            string directory = options.Require("driver-dir");
            string reportPath = UnderRoot(options.Get("report", Path.Combine("local", "oem-probe.json")), "local");
            JsonObject report;
            using (var scanner = OemScanner.Open(directory))
            {
                report = new JsonObject {
                    { "decision", "H8" }, { "probed_utc", DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture) },
                    { "backend", "Biometrika OEM 3.3 x86" }, { "dll_sha256", OemScanner.LibrarySha256 },
                    { "scanner_type", scanner.ScannerType }, { "original_dpi", scanner.OriginalDpi },
                    { "original_capture_configuration", scanner.OriginalCaptureConfiguration },
                    { "requested_dpi", 1000 }, { "readback_dpi", scanner.OutputDpi },
                    { "image_captured", false },
                };
                Console.WriteLine("OEM connection succeeded: scanner type " + scanner.ScannerType + ", DPI " + scanner.OriginalDpi + " -> " + scanner.OutputDpi + ".");
            }
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportPath)));
            File.WriteAllText(reportPath, report.ToJson());
            Console.WriteLine("Probe report: " + Path.GetFullPath(reportPath));
            return 0;
        }

        static int Capture(Options options)
        {
            options.Allow("driver-dir", "session", "finger", "placement", "attempts", "timeout-s", "settle-ms", "out", "initial-delay-s");
            string directory = options.Require("driver-dir"), session = options.Require("session");
            if (!Regex.IsMatch(session, "^[A-Za-z0-9_-]{1,40}$")) throw new UsageException("--session may hold letters, digits, - and _ only.");
            int finger = options.GetInt("finger", 2, 1, 10);
            int placement = options.GetInt("placement", 0, 0, 10); // H9: set by oem-guided, 0 otherwise
            int wanted = options.GetInt("attempts", 1, 1, 20);
            int settle = options.GetInt("settle-ms", 1500, 0, 10000);
            int seconds = options.GetInt("timeout-s", 60, 5, 600);
            int delay = options.GetInt("initial-delay-s", 0, 0, 30);
            string folder = UnderRoot(Path.Combine(options.Get("out", "captures"), session), "captures");
            Directory.CreateDirectory(folder);
            var clock = Stopwatch.StartNew();
            int kept = 0, sequence = 0;
            if (delay > 0) { Console.WriteLine("Capture starts in " + delay + " seconds."); Thread.Sleep(delay * 1000); }
            using (var scanner = OemScanner.Open(directory))
            {
                Console.WriteLine("Connected directly to OEM at 1000 DPI. Waiting for a usable finger image; no driver dialog is used.");
                while (kept < wanted && clock.Elapsed.TotalSeconds < seconds)
                {
                    sequence++;
                    DateTime captured = DateTime.UtcNow;
                    var image = scanner.Capture(settle, out long captureMs);
                    var checks = CaptureChecks.Run(image, 1000, 1000, 1000, scanner.OutputDpi, scanner.OutputDpi, out var detail);
                    bool passed = CaptureChecks.AllPassed(checks);
                    string name = session + "_f" + finger.ToString("00") + (placement > 0 ? "_p" + placement : "") + "_" +
                                  captured.ToString("yyyyMMddTHHmmssfffffff", CultureInfo.InvariantCulture) + "_" + sequence;
                    string target = passed ? folder : Path.Combine(folder, "rejected");
                    Directory.CreateDirectory(target);
                    string png = Path.Combine(target, name + ".png");
                    ImageFiles.SavePng(image, 1000, png);
                    var metadata = new JsonObject {
                        { "decision", placement > 0 ? "H9" : "H8" }, { "file", name + ".png" }, { "sha256", OemScanner.Hash(png) },
                        { "kept", passed }, { "session", session }, { "finger_position", finger }, { "finger", Fingers.Name(finger) },
                        { "placement", placement > 0 ? (object)placement : null }, { "attempt", sequence }, { "captured_utc", captured.ToString("o", CultureInfo.InvariantCulture) },
                        { "backend", "Biometrika OEM 3.3 x86" }, { "dll_sha256", OemScanner.LibrarySha256 },
                        { "scanner_type", scanner.ScannerType }, { "transfer_mode", 1 },
                        { "transfer_row_order", "bottom-up, reversed before checks and saving" },
                        { "requested_ppi", 1000 }, { "readback_ppi", scanner.OutputDpi },
                        { "width", image.Width }, { "height", image.Height }, { "capture_ms", captureMs },
                        { "checks", checks.Select(c => new JsonObject { { "name", c.Name }, { "passed", c.Passed }, { "detail", c.Detail } }).ToList() },
                        { "fine_detail", new JsonObject {
                            { "share", detail.Share }, { "share_after_round_trip", detail.ShareAfterRoundTrip },
                            { "kept", detail.Kept }, { "replicated", detail.Replicated }, { "crop_std", detail.CropStd } } },
                    };
                    using (var output = new StreamWriter(new FileStream(Path.Combine(target, name + ".json"), FileMode.CreateNew, FileAccess.Write)))
                        output.Write(metadata.ToJson());
                    if (passed) kept++;
                    Console.WriteLine((passed ? "KEPT " : "Rejected ") + name + ": " + string.Join("; ", checks.Select(c => c.Name + " " + (c.Passed ? "ok" : "FAILED") + " (" + c.Detail + ")")));
                }
            }
            Console.WriteLine("Completed: " + kept + "/" + wanted + " accepted, " + sequence + " acquired. Folder: " + folder);
            return kept == wanted ? 0 : 3;
        }

        internal static string UnderRoot(string path, string root)
        {
            string full = Path.GetFullPath(path);
            string boundary = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!full.StartsWith(boundary, StringComparison.OrdinalIgnoreCase))
                throw new UsageException("H8: this output must stay inside the ignored " + root + " folder. Run from the repository root.");
            return full;
        }
    }
}
