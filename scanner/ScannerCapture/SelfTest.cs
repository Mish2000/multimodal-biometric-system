using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using ScannerCapture.Imaging;
using ScannerCapture.Oem;

namespace ScannerCapture
{
    /// <summary>Checks of the image code on synthetic images; no scanner and no biometric data needed.</summary>
    static class SelfTest
    {
        public static int Run()
        {
            var tests = new List<KeyValuePair<string, Action>>
            {
                Test("FFT of an impulse and of a cosine", FftBasics),
                Test("BMP: 8-bit bottom-up with padding and a gray palette", Bmp8),
                Test("BMP: 24-bit gray and refusals of color", Bmp24AndColor),
                Test("PNG keeps pixels and 1000 ppi", PngRoundTrip),
                Test("fine detail: synthetic ridges look native", NativeLooksNative),
                Test("fine detail: enlarged images do not", EnlargedDoNotLookNative),
                Test("finger lists", FingerLists),
                Test("JSON order and escapes", JsonOutput),
                Test("native worker Windows argument round trip (H8)", NativeArguments),
                Test("native capture outputs stay in ignored folders (H8)", NativeOutputPaths),
                Test("native transfer rows are stored top-down (H8)", NativeRowOrder),
                Test("guided capture resumes after the kept placements (H9)", GuidedResume),
            };
            int failed = 0;
            foreach (var t in tests)
            {
                try
                {
                    t.Value();
                    Console.WriteLine("ok      " + t.Key);
                }
                catch (Exception ex)
                {
                    failed++;
                    Console.WriteLine("FAILED  " + t.Key + ": " + ex.Message);
                }
            }
            Console.WriteLine(failed == 0 ? "All " + tests.Count + " self-tests passed." : failed + " of " + tests.Count + " self-tests failed.");
            return failed == 0 ? 0 : 1;
        }

        static KeyValuePair<string, Action> Test(string name, Action body) => new KeyValuePair<string, Action>(name, body);

        static void Assert(bool condition, string message)
        {
            if (!condition) throw new Exception(message);
        }

        static void FftBasics()
        {
            int n = 16;
            var re = new double[n];
            var im = new double[n];
            re[0] = 1;
            DetailCheck.Fft(re, im);
            Assert(re.All(v => Math.Abs(v - 1) < 1e-12) && im.All(v => Math.Abs(v) < 1e-12), "impulse should give a flat spectrum");

            for (int i = 0; i < n; i++) { re[i] = Math.Cos(2 * Math.PI * 3 * i / n); im[i] = 0; }
            DetailCheck.Fft(re, im);
            for (int k = 0; k < n; k++)
            {
                double magnitude = Math.Sqrt(re[k] * re[k] + im[k] * im[k]);
                double expected = k == 3 || k == n - 3 ? n / 2.0 : 0;
                Assert(Math.Abs(magnitude - expected) < 1e-9, "cosine energy belongs in bins 3 and " + (n - 3));
            }
        }

        static byte[] MakeBmp(int width, int height, int bitsPerPixel, Func<int, int, byte[]> pixel, byte[][] palette, bool topDown)
        {
            int stride = (width * bitsPerPixel + 31) / 32 * 4;
            int paletteBytes = palette == null ? 0 : 4 * palette.Length;
            int offset = 14 + 40 + paletteBytes;
            var data = new byte[offset + stride * height];
            data[0] = (byte)'B';
            data[1] = (byte)'M';
            BitConverter.GetBytes(data.Length).CopyTo(data, 2);
            BitConverter.GetBytes(offset).CopyTo(data, 10);
            BitConverter.GetBytes(40).CopyTo(data, 14);
            BitConverter.GetBytes(width).CopyTo(data, 18);
            BitConverter.GetBytes(topDown ? -height : height).CopyTo(data, 22);
            BitConverter.GetBytes((short)1).CopyTo(data, 26);
            BitConverter.GetBytes((short)bitsPerPixel).CopyTo(data, 28);
            BitConverter.GetBytes(39370).CopyTo(data, 38);
            BitConverter.GetBytes(39370).CopyTo(data, 42);
            BitConverter.GetBytes(palette == null ? 0 : palette.Length).CopyTo(data, 46);
            for (int i = 0; palette != null && i < palette.Length; i++)
            {
                data[54 + 4 * i] = palette[i][2];
                data[54 + 4 * i + 1] = palette[i][1];
                data[54 + 4 * i + 2] = palette[i][0];
            }
            for (int y = 0; y < height; y++)
            {
                int row = offset + (topDown ? y : height - 1 - y) * stride;
                for (int x = 0; x < width; x++)
                {
                    var bytes = pixel(x, y);
                    Array.Copy(bytes, 0, data, row + x * bytes.Length, bytes.Length);
                }
            }
            return data;
        }

        static void Bmp8()
        {
            // Index i shows gray 255 - i, so a decoder that ignores the palette fails.
            var palette = Enumerable.Range(0, 256).Select(i => new[] { (byte)(255 - i), (byte)(255 - i), (byte)(255 - i) }).ToArray();
            int w = 7, h = 5;
            var bmp = MakeBmp(w, h, 8, (x, y) => new[] { (byte)(10 * y + x) }, palette, false);
            var image = Bmp.DecodeGray(bmp, out var info);
            Assert(image.Width == w && image.Height == h, "size");
            for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++)
                    Assert(image.Pixels[y * w + x] == 255 - (10 * y + x), "pixel (" + x + "," + y + ")");
            Assert(Math.Abs(info.DpiX - 999.998) < 0.01, "BMP resolution");
            Assert(!info.IdentityPalette, "inverted palette is not an identity palette");
        }

        static void Bmp24AndColor()
        {
            int w = 5, h = 3;
            var gray = MakeBmp(w, h, 24, (x, y) => new[] { (byte)(x + 7 * y), (byte)(x + 7 * y), (byte)(x + 7 * y) }, null, true);
            var image = Bmp.DecodeGray(gray, out _);
            Assert(image.Pixels[2 * w + 4] == 4 + 14, "24-bit gray pixel");

            var color = MakeBmp(w, h, 24, (x, y) => new byte[] { 1, 2, 3 }, null, true);
            Assert(Throws(() => Bmp.DecodeGray(color, out _)), "a color image must be refused");

            var tinted = new[] { new byte[] { 0, 0, 0 }, new byte[] { 10, 20, 30 } };
            var paletted = MakeBmp(w, h, 8, (x, y) => new[] { (byte)(x % 2) }, tinted, false);
            Assert(Throws(() => Bmp.DecodeGray(paletted, out _)), "a color palette must be refused");
        }

        static bool Throws(Action action)
        {
            try { action(); return false; }
            catch (InvalidDataException) { return true; }
        }

        static void PngRoundTrip()
        {
            var image = Ridges(64, 3);
            string folder = Path.Combine(Path.GetTempPath(), "ScannerCapture-selftest-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            try
            {
                string path = Path.Combine(folder, "ridges.png");
                ImageFiles.SavePng(image, 1000, path);
                Assert(Throws<IOException>(() => ImageFiles.SavePng(image, 1000, path)), "an existing file must not be overwritten");
                var back = ImageFiles.Load(path, out double dpiX, out double dpiY, out string format);
                Assert(format == "Gray8", "PNG pixel format is " + format);
                Assert(back.Pixels.SequenceEqual(image.Pixels), "pixels changed");
                Assert(Math.Abs(dpiX - 1000) < 0.01 && Math.Abs(dpiY - 1000) < 0.01, "resolution read back as " + dpiX + " x " + dpiY);
            }
            finally
            {
                Directory.Delete(folder, true);
            }
        }

        static bool Throws<T>(Action action) where T : Exception
        {
            try { action(); return false; }
            catch (T) { return true; }
        }

        /// <summary>Curved ridges about 9 pixels apart (as at 1000 ppi) with fine noise.</summary>
        static GrayImage Ridges(int size, int seed)
        {
            var random = new Random(seed);
            var pixels = new byte[size * size];
            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++)
                {
                    double angle = 0.6 + 0.3 * Math.Sin(y / 180.0);
                    double phase = 2 * Math.PI * (x * Math.Cos(angle) + y * Math.Sin(angle)) / 9.0;
                    double v = 128 + 70 * Math.Sin(phase) + 40 * (random.NextDouble() - 0.5);
                    pixels[y * size + x] = (byte)Math.Max(0, Math.Min(255, Math.Round(v)));
                }
            return new GrayImage(size, size, pixels);
        }

        static void NativeLooksNative()
        {
            var d = DetailCheck.Measure(Ridges(1000, 7));
            Assert(DetailCheck.LooksNative(d), "kept " + d.Kept.ToString("0.000") + ", replicated " + d.Replicated.ToString("0.000"));
            Assert(d.CropStd >= DetailCheck.MinCropStd, "ridge texture");
        }

        static void EnlargedDoNotLookNative()
        {
            var native = Ridges(1000, 7);
            var cubic = new GrayImage(1000, 1000, DetailCheck.RoundTrip(native));
            var dc = DetailCheck.Measure(cubic);
            Assert(!DetailCheck.LooksNative(dc) && dc.Kept > DetailCheck.MaxKept, "cubic enlargement kept " + dc.Kept.ToString("0.000"));

            var replicated = new byte[1000 * 1000];
            for (int y = 0; y < 1000; y++)
                for (int x = 0; x < 1000; x++)
                    replicated[y * 1000 + x] = native.Pixels[(y / 2 * 2) * 1000 + x / 2 * 2];
            var dr = DetailCheck.Measure(new GrayImage(1000, 1000, replicated));
            Assert(!DetailCheck.LooksNative(dr) && dr.Replicated > 0.99, "pixel replication gave " + dr.Replicated.ToString("0.000"));
        }

        static void FingerLists()
        {
            Assert(Fingers.Parse("1-10").SequenceEqual(Enumerable.Range(1, 10)), "1-10");
            Assert(Fingers.Parse("2,7-9,2").SequenceEqual(new[] { 2, 7, 8, 9 }), "2,7-9,2");
            Assert(Fingers.Name(6) == "left thumb", "position 6");
            bool refused;
            try { Fingers.Parse("0-3"); refused = false; } catch (UsageException) { refused = true; }
            Assert(refused, "position 0 must be refused");
        }

        static void JsonOutput()
        {
            var json = new JsonObject { { "b", 1 }, { "a", "x\"y\\z" }, { "n", null }, { "list", new[] { 1.5, 2.0 } } }.ToJson();
            string expected = "{\n  \"b\": 1,\n  \"a\": \"x\\\"y\\\\z\",\n  \"n\": null,\n  \"list\": [\n    1.5,\n    2\n  ]\n}\n";
            Assert(json == expected, "got " + json);
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr CommandLineToArgvW(string command, out int argc);
        [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr memory);

        static void NativeArguments()
        {
            string[] expected = { "", "plain", "two words", @"C:\driver with spaces\", "a\"b", "a\\\"b", "עברית", "\\\\", @"C:\plain\" };
            string command = "test.exe " + string.Join(" ", expected.Select(OemCommands.Quote));
            IntPtr argv = CommandLineToArgvW(command, out int count);
            Assert(argv != IntPtr.Zero, "Windows could not parse the command");
            try
            {
                Assert(count == expected.Length + 1, "argument count changed");
                for (int i = 0; i < expected.Length; i++)
                    Assert(Marshal.PtrToStringUni(Marshal.ReadIntPtr(argv, (i + 1) * IntPtr.Size)) == expected[i], "argument " + i + " changed");
            }
            finally { LocalFree(argv); }
        }

        static void NativeOutputPaths()
        {
            Assert(OemCommands.UnderRoot(Path.Combine("captures", "session", "sample.png"), "captures") ==
                Path.GetFullPath(Path.Combine("captures", "session", "sample.png")), "valid capture path");
            Assert(Throws<UsageException>(() => OemCommands.UnderRoot(Path.Combine("captures", "..", "docs", "sample.json"), "captures")), "parent traversal must be refused");
            Assert(Throws<UsageException>(() => OemCommands.UnderRoot(Path.Combine("captures-other", "sample.json"), "captures")), "sibling prefix must be refused");
        }

        static void NativeRowOrder()
        {
            // The first transferred row is the image's bottom row.
            var bottomUp = new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 };
            var topDown = OemScanner.TopDown(bottomUp, 4, 3);
            Assert(topDown.SequenceEqual(new byte[] { 9, 10, 11, 12, 5, 6, 7, 8, 1, 2, 3, 4 }), "rows must be reversed");
            Assert(OemScanner.TopDown(topDown, 4, 3).SequenceEqual(bottomUp), "reversing twice must restore the transfer");
            Assert(Throws<ArgumentException>(() => OemScanner.TopDown(bottomUp, 5, 3)), "a size mismatch must be refused");
        }

        static void GuidedResume()
        {
            string folder = Path.Combine(Path.GetTempPath(), "ScannerCapture-selftest-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(folder, "rejected"));
            try
            {
                Assert(OemCommands.KeptPlacements(Path.Combine(folder, "missing"), "s1", 2) == 0, "a missing folder holds no placements");
                foreach (var name in new[] {
                    "s1_f02_p1_20261019T1600000000000_1.png", "s1_f02_p2_20261019T1601000000000_2.png",
                    "s1_f03_p3_20261019T1602000000000_1.png", "s1_f02_20261019T1603000000000_1.png",
                    Path.Combine("rejected", "s1_f02_p3_20261019T1604000000000_1.png") })
                    File.WriteAllBytes(Path.Combine(folder, name), new byte[0]);
                Assert(OemCommands.KeptPlacements(folder, "s1", 2) == 2, "finger 2: rejected and unguided files must not count");
                Assert(OemCommands.KeptPlacements(folder, "s1", 3) == 3, "finger 3 resumes after its highest placement");
                Assert(OemCommands.KeptPlacements(folder, "s1", 7) == 0, "finger 7 has no placements");
            }
            finally
            {
                Directory.Delete(folder, true);
            }
        }
    }
}
