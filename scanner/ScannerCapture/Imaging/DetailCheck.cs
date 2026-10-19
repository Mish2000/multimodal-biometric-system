using System;

namespace ScannerCapture.Imaging
{
    /// <summary>Fine-detail measures of one image (see <see cref="DetailCheck"/>).</summary>
    sealed class DetailResult
    {
        /// <summary>Share of spectral energy above 0.25 cycles/pixel in the centre crop.</summary>
        public double Share;
        /// <summary>The same share after a 1000 -> 500 -> 1000 ppi round trip.</summary>
        public double ShareAfterRoundTrip;
        /// <summary>ShareAfterRoundTrip / Share: what a 500 ppi round trip leaves of the fine detail.</summary>
        public double Kept;
        /// <summary>Share of constant 2x2 blocks in textured areas, at the worst of the four 2x2 phases.</summary>
        public double Replicated;
        /// <summary>Standard deviation of the centre crop, in gray levels.</summary>
        public double CropStd;
    }

    /// <summary>
    /// Is a capture native 1000 ppi or an enlarged 500 ppi image (H7)? The measure is the one used on
    /// 2026-10-18 for the researcher's first HiScan PRO captures: a native image loses most of its energy
    /// above 0.25 cycles/pixel (the 500 ppi limit) in a 1000 -> 500 -> 1000 round trip, while an image
    /// enlarged from 500 ppi has little to lose. Pixel replication is caught separately, because it adds
    /// blocky detail that the round trip also removes.
    /// Reference on 2026-10-19 (ten 1000 ppi HiScan PRO captures): Kept 0.179-0.212 and Replicated
    /// 0.018-0.044 for the captures; after enlarging them from 500 ppi, Kept 0.476-0.954 (linear),
    /// 0.602-0.721 (cubic), 1.37-1.78 (Lanczos), and Replicated 1.000 (pixel replication).
    /// </summary>
    static class DetailCheck
    {
        public const int CropSize = 512;
        public const double MaxKept = 0.40;
        public const double MaxReplicated = 0.50;
        /// <summary>Below this the crop holds too little ridge texture to judge (the captures: 87-110).</summary>
        public const double MinCropStd = 20.0;
        const int TexturedRange = 8;

        public static DetailResult Measure(GrayImage image)
        {
            if (image.Width < CropSize || image.Height < CropSize)
                throw new ArgumentException("The image is smaller than the " + CropSize + "-pixel crop.");
            var crop = CenterCrop(image.Pixels, image.Width, image.Height);
            var roundTrip = RoundTrip(image);
            var result = new DetailResult
            {
                Share = HighBandShare(crop),
                ShareAfterRoundTrip = HighBandShare(CenterCrop(roundTrip, image.Width, image.Height)),
                Replicated = ReplicatedBlocks(image),
                CropStd = StandardDeviation(crop),
            };
            result.Kept = result.Share > 0 ? result.ShareAfterRoundTrip / result.Share : double.NaN;
            return result;
        }

        public static bool LooksNative(DetailResult r) => r.Kept <= MaxKept && r.Replicated < MaxReplicated;

        static double[] CenterCrop(byte[] pixels, int width, int height)
        {
            int y0 = (height - CropSize) / 2, x0 = (width - CropSize) / 2;
            var crop = new double[CropSize * CropSize];
            for (int y = 0; y < CropSize; y++)
                for (int x = 0; x < CropSize; x++)
                    crop[y * CropSize + x] = pixels[(y0 + y) * width + x0 + x];
            return crop;
        }

        static double StandardDeviation(double[] values)
        {
            double mean = 0;
            foreach (var v in values) mean += v;
            mean /= values.Length;
            double sum = 0;
            foreach (var v in values) sum += (v - mean) * (v - mean);
            return Math.Sqrt(sum / values.Length);
        }

        /// <summary>
        /// Mean removed, Hann window, 2-D FFT; energy above 0.25 cycles/pixel (the larger of the two axis
        /// frequencies) divided by the energy above 0.01 cycles/pixel.
        /// </summary>
        public static double HighBandShare(double[] crop)
        {
            int n = CropSize;
            double mean = 0;
            foreach (var v in crop) mean += v;
            mean /= crop.Length;

            var window = new double[n];
            for (int i = 0; i < n; i++) window[i] = 0.5 - 0.5 * Math.Cos(2 * Math.PI * i / (n - 1));

            var re = new double[n * n];
            var im = new double[n * n];
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++)
                    re[y * n + x] = (crop[y * n + x] - mean) * window[y] * window[x];

            Fft2D(re, im, n);

            double high = 0, total = 0;
            for (int ky = 0; ky < n; ky++)
            {
                double fy = Math.Abs(Frequency(ky, n));
                for (int kx = 0; kx < n; kx++)
                {
                    double r = Math.Max(fy, Math.Abs(Frequency(kx, n)));
                    double p = re[ky * n + kx] * re[ky * n + kx] + im[ky * n + kx] * im[ky * n + kx];
                    if (r > 0.01) total += p;
                    if (r > 0.25) high += p;
                }
            }
            return high / total;
        }

        /// <summary>The frequency of FFT bin k, in cycles/pixel, as numpy.fft.fftfreq gives it.</summary>
        static double Frequency(int k, int n) => (k < n / 2 ? k : k - n) / (double)n;

        static void Fft2D(double[] re, double[] im, int n)
        {
            var rowRe = new double[n];
            var rowIm = new double[n];
            for (int y = 0; y < n; y++)
            {
                Array.Copy(re, y * n, rowRe, 0, n);
                Array.Copy(im, y * n, rowIm, 0, n);
                Fft(rowRe, rowIm);
                Array.Copy(rowRe, 0, re, y * n, n);
                Array.Copy(rowIm, 0, im, y * n, n);
            }
            for (int x = 0; x < n; x++)
            {
                for (int y = 0; y < n; y++) { rowRe[y] = re[y * n + x]; rowIm[y] = im[y * n + x]; }
                Fft(rowRe, rowIm);
                for (int y = 0; y < n; y++) { re[y * n + x] = rowRe[y]; im[y * n + x] = rowIm[y]; }
            }
        }

        /// <summary>In-place radix-2 FFT; the length must be a power of two.</summary>
        public static void Fft(double[] re, double[] im)
        {
            int n = re.Length;
            if ((n & (n - 1)) != 0) throw new ArgumentException("The FFT length must be a power of two.");
            for (int i = 1, j = 0; i < n; i++)
            {
                int bit = n >> 1;
                for (; (j & bit) != 0; bit >>= 1) j ^= bit;
                j ^= bit;
                if (i < j)
                {
                    double t = re[i]; re[i] = re[j]; re[j] = t;
                    t = im[i]; im[i] = im[j]; im[j] = t;
                }
            }
            for (int length = 2; length <= n; length <<= 1)
            {
                int half = length / 2;
                for (int k = 0; k < half; k++)
                {
                    double angle = -2 * Math.PI * k / length;
                    double wr = Math.Cos(angle), wi = Math.Sin(angle);
                    for (int start = 0; start < n; start += length)
                    {
                        int a = start + k, b = a + half;
                        double xr = re[b] * wr - im[b] * wi;
                        double xi = re[b] * wi + im[b] * wr;
                        re[b] = re[a] - xr; im[b] = im[a] - xi;
                        re[a] += xr; im[a] += xi;
                    }
                }
            }
        }

        /// <summary>
        /// 1000 -> 500 -> 1000: 2x2 averages (OpenCV INTER_AREA for an exact factor of 2), then bicubic
        /// enlargement with OpenCV's INTER_CUBIC kernel (A = -0.75, edge pixels repeated).
        /// </summary>
        public static byte[] RoundTrip(GrayImage image)
        {
            int w = image.Width, h = image.Height, hw = w / 2, hh = h / 2;
            var half = new double[hw * hh];
            for (int y = 0; y < hh; y++)
                for (int x = 0; x < hw; x++)
                {
                    int i = 2 * y * w + 2 * x;
                    int sum = image.Pixels[i] + image.Pixels[i + 1] + image.Pixels[i + w] + image.Pixels[i + w + 1];
                    half[y * hw + x] = (sum + 2) >> 2;
                }

            int[] xIndex; double[] xWeight;
            CubicTaps(hw, w, out xIndex, out xWeight);
            var rows = new double[hh * w];
            for (int y = 0; y < hh; y++)
                for (int x = 0; x < w; x++)
                {
                    double v = 0;
                    for (int k = 0; k < 4; k++) v += xWeight[4 * x + k] * half[y * hw + xIndex[4 * x + k]];
                    rows[y * w + x] = v;
                }

            int[] yIndex; double[] yWeight;
            CubicTaps(hh, h, out yIndex, out yWeight);
            var result = new byte[w * h];
            for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++)
                {
                    double v = 0;
                    for (int k = 0; k < 4; k++) v += yWeight[4 * y + k] * rows[yIndex[4 * y + k] * w + x];
                    result[y * w + x] = (byte)Math.Max(0, Math.Min(255, Math.Round(v)));
                }
            return result;
        }

        static void CubicTaps(int sourceSize, int targetSize, out int[] index, out double[] weight)
        {
            const double A = -0.75;
            double scale = sourceSize / (double)targetSize;
            index = new int[4 * targetSize];
            weight = new double[4 * targetSize];
            for (int d = 0; d < targetSize; d++)
            {
                double f = (d + 0.5) * scale - 0.5;
                int s = (int)Math.Floor(f);
                double t = f - s;
                double w0 = ((A * (t + 1) - 5 * A) * (t + 1) + 8 * A) * (t + 1) - 4 * A;
                double w1 = ((A + 2) * t - (A + 3)) * t * t + 1;
                double w2 = ((A + 2) * (1 - t) - (A + 3)) * (1 - t) * (1 - t) + 1;
                double w3 = 1 - w0 - w1 - w2;
                double[] ws = { w0, w1, w2, w3 };
                for (int k = 0; k < 4; k++)
                {
                    index[4 * d + k] = Math.Max(0, Math.Min(sourceSize - 1, s - 1 + k));
                    weight[4 * d + k] = ws[k];
                }
            }
        }

        /// <summary>
        /// For each of the four 2x2 phases: among 4x4 windows with a gray range of at least 8 (flat and
        /// saturated areas are left out), the share of their 2x2 blocks whose four pixels are equal.
        /// The largest share over the phases is returned; pixel replication gives 1.
        /// </summary>
        public static double ReplicatedBlocks(GrayImage image)
        {
            int w = image.Width;
            var p = image.Pixels;
            double best = 0;
            for (int oy = 0; oy < 2; oy++)
                for (int ox = 0; ox < 2; ox++)
                {
                    long blocks = 0, constant = 0;
                    for (int wy = oy; wy + 4 <= image.Height; wy += 4)
                        for (int wx = ox; wx + 4 <= w; wx += 4)
                        {
                            int min = 255, max = 0;
                            for (int y = 0; y < 4; y++)
                                for (int x = 0; x < 4; x++)
                                {
                                    int v = p[(wy + y) * w + wx + x];
                                    if (v < min) min = v;
                                    if (v > max) max = v;
                                }
                            if (max - min < TexturedRange) continue;
                            for (int by = 0; by < 4; by += 2)
                                for (int bx = 0; bx < 4; bx += 2)
                                {
                                    int i = (wy + by) * w + wx + bx;
                                    blocks++;
                                    if (p[i] == p[i + 1] && p[i] == p[i + w] && p[i] == p[i + w + 1]) constant++;
                                }
                        }
                    if (blocks > 0) best = Math.Max(best, constant / (double)blocks);
                }
            return best;
        }
    }
}
