using System;
using System.Collections.Generic;

namespace ScannerCapture.Imaging
{
    /// <summary>One named check with its outcome and the measured value.</summary>
    sealed class CheckResult
    {
        public CheckResult(string name, bool passed, string detail)
        {
            Name = name;
            Passed = passed;
            Detail = detail;
        }

        public string Name { get; }
        public bool Passed { get; }
        public string Detail { get; }
    }

    /// <summary>
    /// The checks every capture must pass before it is kept (H7): the expected size, the resolution the
    /// scanner reports, enough ridge texture in the centre, and fine detail of a native 1000 ppi image.
    /// </summary>
    static class CaptureChecks
    {
        public static List<CheckResult> Run(GrayImage image, int expectedWidth, int expectedHeight,
            double expectedPpi, double reportedPpiX, double reportedPpiY, out DetailResult detail)
        {
            var results = new List<CheckResult>
            {
                new CheckResult("size", image.Width == expectedWidth && image.Height == expectedHeight,
                    image.Width + "x" + image.Height + " (expected " + expectedWidth + "x" + expectedHeight + ")"),
                new CheckResult("resolution",
                    Math.Abs(reportedPpiX - expectedPpi) < 0.5 && Math.Abs(reportedPpiY - expectedPpi) < 0.5,
                    Number(reportedPpiX) + "x" + Number(reportedPpiY) + " ppi (expected " + Number(expectedPpi) + ")"),
            };

            detail = null;
            if (image.Width < DetailCheck.CropSize || image.Height < DetailCheck.CropSize)
            {
                results.Add(new CheckResult("fine detail", false, "image smaller than the " + DetailCheck.CropSize + "-pixel crop"));
                return results;
            }

            detail = DetailCheck.Measure(image);
            results.Add(new CheckResult("ridge texture", detail.CropStd >= DetailCheck.MinCropStd,
                "centre spread " + detail.CropStd.ToString("0.0") + " gray levels (at least " + DetailCheck.MinCropStd + ")"));
            results.Add(new CheckResult("fine detail", DetailCheck.LooksNative(detail),
                "a 500 ppi round trip keeps " + detail.Kept.ToString("0.000") + " (at most " + DetailCheck.MaxKept.ToString("0.00") +
                "); replicated pixels " + detail.Replicated.ToString("0.000") + " (below " + DetailCheck.MaxReplicated.ToString("0.00") + ")"));
            return results;
        }

        public static bool AllPassed(IEnumerable<CheckResult> results)
        {
            foreach (var r in results) if (!r.Passed) return false;
            return true;
        }

        static string Number(double value) => Math.Abs(value - Math.Round(value)) < 0.01
            ? Math.Round(value).ToString("0")
            : value.ToString("0.00");
    }
}
