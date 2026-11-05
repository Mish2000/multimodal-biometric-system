using System.IO;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace ScannerCapture.Imaging
{
    /// <summary>PNG writing and image reading through WPF imaging (Windows Imaging Component).</summary>
    static class ImageFiles
    {
        /// <summary>
        /// Writes an 8-bit gray PNG (lossless) whose pHYs chunk carries the resolution. Never overwrites a file.
        /// </summary>
        public static void SavePng(GrayImage image, double dpi, string path)
        {
            var source = BitmapSource.Create(image.Width, image.Height, dpi, dpi, PixelFormats.Gray8, null,
                image.Pixels, image.Width);
            var encoder = new PngBitmapEncoder { Interlace = PngInterlaceOption.Off };
            encoder.Frames.Add(BitmapFrame.Create(source));
            using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write))
            {
                encoder.Save(stream);
            }
        }

        /// <summary>
        /// The same 8-bit gray PNG with its resolution, in memory: the acquisition mode returns it to the server
        /// without writing a file (H13, H33).
        /// </summary>
        public static byte[] EncodePng(GrayImage image, double dpi)
        {
            var source = BitmapSource.Create(image.Width, image.Height, dpi, dpi, PixelFormats.Gray8, null,
                image.Pixels, image.Width);
            var encoder = new PngBitmapEncoder { Interlace = PngInterlaceOption.Off };
            encoder.Frames.Add(BitmapFrame.Create(source));
            using (var stream = new MemoryStream())
            {
                encoder.Save(stream);
                return stream.ToArray();
            }
        }

        /// <summary>Reads the first frame of a PNG, TIFF or BMP file as gray pixels, with its resolution.</summary>
        public static GrayImage Load(string path, out double dpiX, out double dpiY, out string pixelFormat)
        {
            using (var stream = File.OpenRead(path))
                return Load(stream, out dpiX, out dpiY, out pixelFormat);
        }

        /// <summary>The same from a stream, for example a PNG kept in memory.</summary>
        public static GrayImage Load(Stream stream, out double dpiX, out double dpiY, out string pixelFormat)
        {
            {
                var decoder = BitmapDecoder.Create(stream,
                    BitmapCreateOptions.PreservePixelFormat | BitmapCreateOptions.IgnoreColorProfile,
                    BitmapCacheOption.OnLoad);
                BitmapSource frame = decoder.Frames[0];
                dpiX = frame.DpiX;
                dpiY = frame.DpiY;
                pixelFormat = frame.Format.ToString();
                if (frame.Format != PixelFormats.Gray8)
                {
                    frame = new FormatConvertedBitmap(frame, PixelFormats.Gray8, null, 0);
                }
                var pixels = new byte[frame.PixelWidth * frame.PixelHeight];
                frame.CopyPixels(pixels, frame.PixelWidth, 0);
                return new GrayImage(frame.PixelWidth, frame.PixelHeight, pixels);
            }
        }
    }
}
