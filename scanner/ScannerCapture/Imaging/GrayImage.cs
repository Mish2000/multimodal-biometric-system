using System;

namespace ScannerCapture.Imaging
{
    /// <summary>An 8-bit grayscale image: rows from top to bottom, no row padding.</summary>
    sealed class GrayImage
    {
        public GrayImage(int width, int height, byte[] pixels)
        {
            if (width <= 0 || height <= 0) throw new ArgumentException("Image size must be positive.");
            if (pixels == null || pixels.Length != width * height)
                throw new ArgumentException("The pixel count does not match the image size.");
            Width = width;
            Height = height;
            Pixels = pixels;
        }

        public int Width { get; }
        public int Height { get; }
        public byte[] Pixels { get; }
    }
}
