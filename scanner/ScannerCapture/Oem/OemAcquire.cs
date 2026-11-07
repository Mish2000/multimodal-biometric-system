using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using ScannerCapture.Imaging;

namespace ScannerCapture.Oem
{
    /// <summary>
    /// H13, H33: the server's acquisition mode. One run either waits for a placed finger and returns its checked
    /// 1000 ppi image, or waits until the finger is lifted off the glass. Every message goes to standard output
    /// as one line of JSON; an image follows its line as PNG bytes. No file is written, so a raw capture exists
    /// on disk only after the server has sealed it. The server is the watchdog: it stops a run that exceeds its
    /// deadline, and it retries a run that fails with OEM status 110 once (H9).
    /// </summary>
    static class OemAcquire
    {
        // H33: a finger is lifted when two frames in a row have no ridge texture, since the first frame of a new
        // connection can be blank while the finger is still on the glass (H8).
        const int EmptyFramesForLift = 2;

        public static int Run(Options options)
        {
            options.Allow("driver-dir", "wait", "timeout-s", "settle-ms", "cancel-stdin");
            string directory = options.Require("driver-dir");
            string wait = options.Get("wait", "finger").ToLowerInvariant();
            if (wait != "finger" && wait != "lift") throw new UsageException("--wait must be finger or lift.");
            int seconds = options.GetInt("timeout-s", 30, 1, 600);
            int settle = options.GetInt("settle-ms", 1500, 0, 10000);
            var output = Console.OpenStandardOutput();
            // H36: the server closes stdin to request a graceful stop. Only this worker thread makes
            // native calls; the reader sets a flag, so cleanup never races an acquisition in the OEM DLL.
            var cancellation = new CancellationTokenSource();
            if (options.Get("cancel-stdin", "no") == "yes")
            {
                if (!Console.IsInputRedirected) throw new UsageException("--cancel-stdin needs redirected input.");
                var reader = new Thread(() => ReadCancellation(Console.In, cancellation)) { IsBackground = true };
                reader.Start();
            }
            try
            {
                using (var mutex = new Mutex(false, @"Local\MultimodalBiometricSystem.HiScan.H8"))
                {
                    bool acquired;
                    try { acquired = mutex.WaitOne(0); }
                    catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) throw new IOException("Another native scanner command is running.");
                    try { return Acquire(directory, wait == "lift", seconds, settle, output, cancellation.Token); }
                    finally { mutex.ReleaseMutex(); }
                }
            }
            catch (UsageException) { throw; }
            catch (Exception ex) { Console.Error.WriteLine(ex.Message); return 2; }
        }

        internal static void ReadCancellation(TextReader input, CancellationTokenSource cancellation)
        {
            try { input.ReadLine(); }
            catch (IOException) { }
            finally { cancellation.Cancel(); }
        }

        static int Acquire(string directory, bool lift, int seconds, int settle, Stream output, CancellationToken cancellation)
        {
            var clock = Stopwatch.StartNew();
            if (cancellation.IsCancellationRequested) return 4;
            using (var scanner = OemScanner.Open(directory))
            {
                Write(output, new JsonObject { { "event", "ready" }, { "wait", lift ? "lift" : "finger" }, { "ppi", scanner.OutputDpi } }, null);
                int frames = 0, empty = 0;
                while (clock.Elapsed.TotalSeconds < seconds)
                {
                    if (cancellation.IsCancellationRequested) return 4;
                    frames++;
                    var image = scanner.Capture(settle, out long captureMs);
                    if (cancellation.IsCancellationRequested) return 4; // Dispose restores settings and closes the channel
                    var checks = CaptureChecks.Run(image, 1000, 1000, 1000, scanner.OutputDpi, scanner.OutputDpi, out var detail);
                    if (lift)
                    {
                        bool finger = checks.Any(c => c.Name == "ridge texture" && c.Passed);
                        empty = finger ? 0 : empty + 1;
                        if (empty >= EmptyFramesForLift)
                        {
                            Write(output, new JsonObject { { "event", "lifted" }, { "frames", frames } }, null);
                            return 0;
                        }
                        Write(output, new JsonObject { { "event", "frame" }, { "finger", finger } }, null);
                        continue;
                    }
                    var list = checks.Select(c => new JsonObject { { "name", c.Name }, { "passed", c.Passed }, { "detail", c.Detail } }).ToList();
                    if (!CaptureChecks.AllPassed(checks))
                    {
                        Write(output, new JsonObject { { "event", "frame" }, { "kept", false }, { "checks", list } }, null);
                        continue;
                    }
                    byte[] png = ImageFiles.EncodePng(image, 1000);
                    Write(output, new JsonObject {
                        { "event", "image" }, { "width", image.Width }, { "height", image.Height }, { "ppi", scanner.OutputDpi },
                        { "capture_ms", captureMs }, { "frames", frames }, { "checks", list },
                        { "fine_detail", new JsonObject {
                            { "share", detail.Share }, { "share_after_round_trip", detail.ShareAfterRoundTrip },
                            { "kept", detail.Kept }, { "replicated", detail.Replicated }, { "crop_std", detail.CropStd } } },
                        { "backend", "Biometrika OEM 3.3 x86" }, { "dll_sha256", OemScanner.LibrarySha256 },
                        { "length", png.Length } }, png);
                    return 0;
                }
                Write(output, new JsonObject { { "event", "timeout" }, { "frames", frames } }, null);
                return 3;
            }
        }

        /// <summary>One message: a line of JSON, then its payload, if any.</summary>
        internal static void Write(Stream output, JsonObject header, byte[] payload)
        {
            byte[] line = Encoding.UTF8.GetBytes(header.ToJsonLine() + "\n");
            output.Write(line, 0, line.Length);
            if (payload != null) output.Write(payload, 0, payload.Length);
            output.Flush();
        }
    }
}
