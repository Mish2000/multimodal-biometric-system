using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Threading;
using ScannerCapture.Imaging;

namespace ScannerCapture.Oem
{
    /// <summary>H8: the supplied x86 OEM 3.3 ABI, recovered from its implementation and TWAIN call sites.</summary>
    sealed class OemScanner : IDisposable
    {
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int NoArgs();
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int SetInt(int value);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetInt(out int value);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetBytes(IntPtr value);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int RandomBytes(IntPtr value, int length);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Transfer(IntPtr nonce, IntPtr pixels, out int width, out int height, byte mode);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int SensorConfig(byte register, byte operation, ushort value, out ushort result);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)]
        static extern IntPtr GetProcAddress(IntPtr module, string name);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool FreeLibrary(IntPtr module);

        readonly IntPtr[] modules = new IntPtr[3];
        NoArgs end, close, capture;
        SetInt setDpi;
        GetInt getDpi;
        RandomBytes random;
        Transfer transfer;
        SensorConfig sensorConfig;
        ushort originalCaptureConfig;
        bool captureConfigured;
        bool initialized, opened, disposed;
        int originalDpi;

        public const string LibrarySha256 = "f18c871610d68a94d15837625581c118ee5c2238a41627b522601376bdbd2903";
        public int ScannerType { get; private set; }
        public int OutputDpi { get; private set; }
        public int OriginalDpi => originalDpi;
        public int OriginalCaptureConfiguration => originalCaptureConfig;

        public static OemScanner Open(string directory)
        {
            if (Environment.Is64BitProcess) throw new InvalidOperationException("The researched OEM 3.3 interface requires the x86 build.");
            var scanner = new OemScanner();
            try
            {
                // H8: pin all three non-system DLLs to the supplied, inspected x86 package.
                string[] names = { "ftd2xx.dll", "CheckPortUSB.dll", "fxoemdll.dll" };
                string[] hashes = {
                    "a7d64886de70ba593d22b0ef17c039ccd93894240a85b5fed668c85aa98376f2",
                    "1da9bcc30d4075aecee5773a9b239fe790b511a34799d8663bb5f13f7bf952ad",
                    LibrarySha256 };
                directory = Path.GetFullPath(directory);
                for (int i = 0; i < names.Length; i++)
                {
                    string path = Path.Combine(directory, names[i]);
                    if (Hash(path) != hashes[i]) throw new InvalidDataException("Unrecognized " + names[i] + "; use the inspected Windows driver 3.3 package.");
                }
                for (int i = 0; i < names.Length; i++)
                {
                    // Search the explicit DLL directory and trusted system/application directories, not the current directory.
                    scanner.modules[i] = LoadLibraryEx(Path.Combine(directory, names[i]), IntPtr.Zero, 0x1100);
                    if (scanner.modules[i] == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot load " + names[i]);
                }
                scanner.end = scanner.Bind<NoArgs>("FXOEM_End");
                scanner.close = scanner.Bind<NoArgs>("FXOEM_CloseStandbyChannel");
                scanner.capture = scanner.Bind<NoArgs>("FXOEM_CaptureImage");
                scanner.setDpi = scanner.Bind<SetInt>("FXOEM_SetOutputDPI");
                scanner.getDpi = scanner.Bind<GetInt>("FXOEM_GetOutputDPI");
                scanner.random = scanner.Bind<RandomBytes>("FXOEM_RandomString");
                scanner.transfer = scanner.Bind<Transfer>("FXOEM_TransferImageNormal");
                scanner.sensorConfig = scanner.Bind<SensorConfig>("FXOEM_SensorConfiguration");
                Check(scanner.Bind<NoArgs>("FXOEM_Init")(), "FXOEM_Init");
                scanner.initialized = true;
                Check(scanner.Bind<NoArgs>("FXOEM_OpenChannel")(), "FXOEM_OpenChannel");
                scanner.opened = true;
                using (var info = new NativeBuffer(64))
                {
                    Check(scanner.Bind<GetBytes>("FXOEM_GetScannerInfo")(info.Pointer), "FXOEM_GetScannerInfo");
                    info.CheckGuard();
                    scanner.ScannerType = Marshal.ReadByte(info.Pointer, 1);
                }
                // H8: SetOutputDPI's type-8 branch explicitly accepts 500 and 1000; other models are not validated.
                if (scanner.ScannerType != 8) throw new InvalidDataException("Expected HiScan PRO (OEM type 8), received type " + scanner.ScannerType + ".");
                // H8: twBiometrika.ds RVA 0x2BC11 enables the capture configuration before acquiring.
                // Read the existing value first so cleanup can restore it.
                Check(scanner.sensorConfig(0x32, 1, 0, out scanner.originalCaptureConfig), "Read capture configuration");
                Check(scanner.sensorConfig(0x32, 2, 0x80, out _), "Enable capture configuration");
                scanner.captureConfigured = true;
                Check(scanner.getDpi(out scanner.originalDpi), "FXOEM_GetOutputDPI");
                Check(scanner.setDpi(1000), "FXOEM_SetOutputDPI(1000)");
                Check(scanner.getDpi(out int actual), "FXOEM_GetOutputDPI");
                if (actual != 1000) throw new InvalidDataException("The OEM library holds " + actual + " DPI instead of 1000.");
                scanner.OutputDpi = actual;
                return scanner;
            }
            catch { scanner.Dispose(); throw; }
        }

        public GrayImage Capture(int settleMs, out long elapsedMs)
        {
            if (disposed) throw new ObjectDisposedException(nameof(OemScanner));
            var clock = Stopwatch.StartNew();
            // H8: TWAIN's caller generates a 16-byte nonce and uses transfer mode 1 (full sensor frame).
            // The type-8 normalized output is bounded at 1000x1000; retain substantial headroom and a guard.
            using (var nonce = new NativeBuffer(16))
            using (var pixels = new NativeBuffer(4 * 1024 * 1024))
            {
                Check(capture(), "FXOEM_CaptureImage");
                if (settleMs > 0) Thread.Sleep(settleMs);
                Check(random(nonce.Pointer, 16), "FXOEM_RandomString");
                Check(transfer(nonce.Pointer, pixels.Pointer, out int width, out int height, 1), "FXOEM_TransferImageNormal");
                nonce.CheckGuard();
                pixels.CheckGuard();
                Check(getDpi(out int dpi), "FXOEM_GetOutputDPI");
                if (dpi != 1000 || width != 1000 || height != 1000)
                    throw new InvalidDataException("OEM output is " + width + "x" + height + " at " + dpi + " DPI; expected native 1000x1000 at 1000.");
                elapsedMs = clock.ElapsedMilliseconds;
                return new GrayImage(width, height, pixels.Read(checked(width * height)));
            }
        }

        T Bind<T>(string name) where T : class
        {
            IntPtr entry = GetProcAddress(modules[2], name);
            if (entry == IntPtr.Zero) throw new EntryPointNotFoundException(name);
            return Marshal.GetDelegateForFunctionPointer(entry, typeof(T)) as T;
        }

        static void Check(int code, string operation)
        {
            if (code != 0) throw new IOException(operation + " failed with OEM status " + code + ".");
        }

        internal static string Hash(string path)
        {
            using (var sha = SHA256.Create())
            using (var file = File.OpenRead(path))
                return BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            int restoreDpi = 0, restoreCapture = 0, closed = 0, ended = 0;
            try
            {
                if (opened)
                {
                    if (originalDpi == 500 || originalDpi == 1000) restoreDpi = setDpi(originalDpi);
                    if (captureConfigured) restoreCapture = sensorConfig(0x32, 2, originalCaptureConfig, out _);
                    closed = close();
                }
            }
            finally
            {
                if (initialized) ended = end();
                for (int i = modules.Length - 1; i >= 0; i--) if (modules[i] != IntPtr.Zero) FreeLibrary(modules[i]);
            }
            if (restoreDpi != 0 || restoreCapture != 0 || closed != 0 || ended != 0)
                Console.Error.WriteLine("OEM cleanup statuses: restore DPI=" + restoreDpi + ", restore capture=" + restoreCapture + ", close=" + closed + ", end=" + ended + ".");
        }

        /// <summary>Unmanaged output storage with a checked tail; this is not a substitute for a verified ABI.</summary>
        sealed class NativeBuffer : IDisposable
        {
            readonly int capacity;
            public IntPtr Pointer { get; }
            public NativeBuffer(int capacity)
            {
                this.capacity = capacity;
                Pointer = Marshal.AllocHGlobal(checked(capacity + 64));
                var zero = new byte[capacity];
                Marshal.Copy(zero, 0, Pointer, capacity);
                for (int i = 0; i < 64; i++) Marshal.WriteByte(Pointer, capacity + i, 0xA5);
            }
            public void CheckGuard()
            {
                for (int i = 0; i < 64; i++)
                    if (Marshal.ReadByte(Pointer, capacity + i) != 0xA5) throw new InvalidDataException("The OEM library exceeded its expected output buffer.");
            }
            public byte[] Read(int count)
            {
                if (count < 0 || count > capacity) throw new ArgumentOutOfRangeException(nameof(count));
                var data = new byte[count];
                Marshal.Copy(Pointer, data, 0, count);
                return data;
            }
            public void Dispose() { Marshal.FreeHGlobal(Pointer); }
        }
    }
}
