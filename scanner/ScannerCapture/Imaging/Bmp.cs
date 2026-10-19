using System;
using System.IO;

namespace ScannerCapture.Imaging
{
    /// <summary>What the BMP header of a transferred image says about it.</summary>
    sealed class BmpInfo
    {
        public int BitsPerPixel;
        public bool TopDown;
        public double DpiX;
        public double DpiY;
        public int PaletteEntries;
        public bool IdentityPalette;
    }

    /// <summary>
    /// Decodes the BMP that NTwain builds from a native (DIB) transfer into gray pixels without loss:
    /// 8-bit images map through their palette, which must be gray; 24-bit images must have R = G = B.
    /// Anything else is refused rather than converted.
    /// </summary>
    static class Bmp
    {
        public static GrayImage DecodeGray(byte[] data, out BmpInfo info)
        {
            if (data == null || data.Length < 54 || data[0] != (byte)'B' || data[1] != (byte)'M')
                throw new InvalidDataException("The transferred data is not a BMP image.");

            int pixelOffset = BitConverter.ToInt32(data, 10);
            int headerSize = BitConverter.ToInt32(data, 14);
            if (headerSize < 40) throw new InvalidDataException("Unsupported BMP header (size " + headerSize + ").");
            int width = BitConverter.ToInt32(data, 18);
            int rawHeight = BitConverter.ToInt32(data, 22);
            int bitsPerPixel = BitConverter.ToInt16(data, 28);
            int compression = BitConverter.ToInt32(data, 30);
            int xPelsPerMeter = BitConverter.ToInt32(data, 38);
            int yPelsPerMeter = BitConverter.ToInt32(data, 42);
            int colorsUsed = BitConverter.ToInt32(data, 46);

            if (compression != 0)
                throw new InvalidDataException("Compressed BMP data (type " + compression + ") is not supported.");
            if (width <= 0 || rawHeight == 0) throw new InvalidDataException("The BMP has no pixels.");

            bool topDown = rawHeight < 0;
            int height = Math.Abs(rawHeight);
            int stride = (width * bitsPerPixel + 31) / 32 * 4;
            if (pixelOffset < 0 || pixelOffset + (long)stride * height > data.Length)
                throw new InvalidDataException("The BMP pixel data is truncated.");

            info = new BmpInfo
            {
                BitsPerPixel = bitsPerPixel,
                TopDown = topDown,
                DpiX = xPelsPerMeter * 0.0254,
                DpiY = yPelsPerMeter * 0.0254,
            };

            var pixels = new byte[width * height];
            if (bitsPerPixel == 8)
            {
                int entries = colorsUsed > 0 ? colorsUsed : 256;
                int paletteOffset = 14 + headerSize;
                if (entries > 256 || paletteOffset + 4 * entries > pixelOffset)
                    throw new InvalidDataException("The BMP palette is malformed.");
                var gray = new byte[256];
                bool identity = entries == 256;
                for (int i = 0; i < entries; i++)
                {
                    byte b = data[paletteOffset + 4 * i];
                    byte g = data[paletteOffset + 4 * i + 1];
                    byte r = data[paletteOffset + 4 * i + 2];
                    if (r != g || g != b)
                        throw new InvalidDataException("The palette is not gray; storing the image as gray would lose data.");
                    gray[i] = r;
                    if (r != i) identity = false;
                }
                info.PaletteEntries = entries;
                info.IdentityPalette = identity;

                for (int y = 0; y < height; y++)
                {
                    int src = pixelOffset + (topDown ? y : height - 1 - y) * stride;
                    int dst = y * width;
                    for (int x = 0; x < width; x++)
                    {
                        int index = data[src + x];
                        if (index >= entries) throw new InvalidDataException("A pixel refers to a missing palette entry.");
                        pixels[dst + x] = gray[index];
                    }
                }
            }
            else if (bitsPerPixel == 24)
            {
                for (int y = 0; y < height; y++)
                {
                    int src = pixelOffset + (topDown ? y : height - 1 - y) * stride;
                    int dst = y * width;
                    for (int x = 0; x < width; x++)
                    {
                        byte b = data[src + 3 * x], g = data[src + 3 * x + 1], r = data[src + 3 * x + 2];
                        if (r != g || g != b)
                            throw new InvalidDataException("The image has color; storing it as gray would lose data.");
                        pixels[dst + x] = r;
                    }
                }
            }
            else
            {
                throw new InvalidDataException(bitsPerPixel + "-bit BMP data is not supported; the scanner should deliver 8-bit gray.");
            }

            return new GrayImage(width, height, pixels);
        }
    }
}
