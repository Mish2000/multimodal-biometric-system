using System;
using System.Diagnostics;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using NTwain;
using NTwain.Data;

namespace ScannerCapture.Twain
{
    /// <summary>A failure that ends the command with a specific exit code.</summary>
    sealed class ScannerException : Exception
    {
        public ScannerException(int exitCode, string message) : base(message) { ExitCode = exitCode; }

        public int ExitCode { get; }
    }

    /// <summary>
    /// An open TWAIN session on a hidden window's message loop. Every TWAIN call runs on this one thread,
    /// as in a classic TWAIN application, and the source's messages reach NTwain through the loop.
    /// </summary>
    sealed class TwainHost : IDisposable
    {
        TwainHost(IntPtr windowHandle)
        {
            WindowHandle = windowHandle;
            // TWAIN identity strings hold at most 32 characters.
            var version = Assembly.GetExecutingAssembly().GetName().Version;
            Session = new TwainSession(TWIdentity.Create(DataGroups.Image, version, "multimodal-biometric-system",
                "Scanner capture", "ScannerCapture", "ScannerCapture " + version.ToString(3)));
            var rc = Session.Open(new WindowsFormsMessageLoopHook(windowHandle));
            if (rc != ReturnCode.Success)
            {
                throw new ScannerException(2, "The TWAIN manager did not open (rc=" + rc + ", " +
                    PlatformInfo.Current.ExpectedDsmPath + ").");
            }
        }

        public TwainSession Session { get; }
        public IntPtr WindowHandle { get; }

        public void Dispose()
        {
            if (Session.State > 4) Session.ForceStepDown(4);
            if (Session.State == 4) Session.CurrentSource?.Close();
            if (Session.IsDsmOpen) Session.Close();
        }

        /// <summary>Runs the body inside a Windows Forms message loop and returns its exit code.</summary>
        public static int Run(Func<TwainHost, int> body)
        {
            int exitCode = 1;
            using (var window = new Form { ShowInTaskbar = false, Text = "ScannerCapture" })
            {
                var handle = window.Handle; // creates the hidden window that TWAIN posts to
                var context = new ApplicationContext();
                window.BeginInvoke(new Action(() =>
                {
                    try
                    {
                        using (var host = new TwainHost(handle))
                        {
                            exitCode = body(host);
                        }
                    }
                    catch (ScannerException ex)
                    {
                        Console.Error.WriteLine(ex.Message);
                        exitCode = ex.ExitCode;
                    }
                    catch (Exception ex)
                    {
                        Console.Error.WriteLine("Unexpected error: " + ex);
                        exitCode = 1;
                    }
                    finally
                    {
                        context.ExitThread();
                    }
                }));
                Application.Run(context);
            }
            return exitCode;
        }

        /// <summary>Keeps Windows and TWAIN messages flowing until done() is true or the time runs out.</summary>
        public static bool PumpUntil(Func<bool> done, TimeSpan timeout)
        {
            var clock = Stopwatch.StartNew();
            while (!done())
            {
                if (clock.Elapsed >= timeout) return false;
                Application.DoEvents();
                Thread.Sleep(5);
            }
            return true;
        }

        /// <summary>Waits while keeping messages flowing, so the source stays responsive.</summary>
        public static void PumpFor(TimeSpan duration)
        {
            if (duration > TimeSpan.Zero) PumpUntil(() => false, duration);
        }
    }
}
