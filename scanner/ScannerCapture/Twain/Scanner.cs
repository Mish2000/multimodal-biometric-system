using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using NTwain;
using NTwain.Data;

namespace ScannerCapture.Twain
{
    /// <summary>The result of one enable-transfer-disable cycle.</summary>
    sealed class CaptureOutcome
    {
        /// <summary>The transferred image as a BMP file (NTwain adds the file header to the DIB).</summary>
        public byte[] Bmp;
        /// <summary>DAT_IMAGEINFO as the source reported it during the transfer.</summary>
        public TWImageInfo ImageInfo;
        /// <summary>Null when an image arrived.</summary>
        public string Error;
        /// <summary>Milliseconds from enabling the source to its transfer-ready message; -1 if none came.</summary>
        public long TransferReadyAfterMs = -1;
        /// <summary>Extra wait before the transfer so the image is taken at least the settle time after enabling.</summary>
        public long SettleWaitMs;
        public long TotalMs;
    }

    /// <summary>The scanner's TWAIN data source: capability reports, negotiation, capture and saved settings.</summary>
    sealed class Scanner : IDisposable
    {
        /// <summary>The name the Biometrika driver registers (the Stage A helper confirmed it on this PC).</summary>
        public const string DefaultSourceName = "TWAIN Biometrika Driver";

        readonly TwainHost _host;

        Scanner(TwainHost host, DataSource source)
        {
            _host = host;
            Source = source;
        }

        public DataSource Source { get; }

        public static Scanner Open(TwainHost host, string name)
        {
            var sources = host.Session.GetSources().ToList();
            var source = sources.FirstOrDefault(s => s.Name == name);
            if (source == null)
            {
                throw new ScannerException(2, "The TWAIN source \"" + name + "\" is not installed. Installed: " +
                    (sources.Count == 0 ? "none" : string.Join(", ", sources.Select(s => "\"" + s.Name + "\""))) + ".");
            }
            var rc = source.Open();
            if (rc != ReturnCode.Success)
            {
                throw new ScannerException(2, "The TWAIN source \"" + name + "\" did not open (rc=" + rc + ", condition=" +
                    host.Session.GetStatus().ConditionCode + "). Is the scanner plugged in?");
            }
            return new Scanner(host, source);
        }

        public void Dispose()
        {
            if (_host.Session.State > 4) _host.Session.ForceStepDown(4);
            if (Source.IsOpen) Source.Close();
        }

        public List<string> SupportedCapabilities()
        {
            try
            {
                return Source.Capabilities.CapSupportedCaps.GetValues().Select(c => c.ToString()).ToList();
            }
            catch (Exception ex)
            {
                return new List<string> { "error: " + ex.Message };
            }
        }

        /// <summary>Every capability this tool relies on, as the source describes it.</summary>
        public List<KeyValuePair<string, string>> DescribeCapabilities()
        {
            var c = Source.Capabilities;
            var list = new List<KeyValuePair<string, string>>();
            void Add<T>(string name, IReadOnlyCapWrapper<T> cap) => list.Add(new KeyValuePair<string, string>(name, Describe(cap)));
            Add("CAP_DEVICEONLINE", c.CapDeviceOnline);
            Add("CAP_UICONTROLLABLE", c.CapUIControllable);
            Add("CAP_ENABLEDSUIONLY", c.CapEnableDSUIOnly);
            Add("CAP_CUSTOMDSDATA", c.CapCustomDSData);
            Add("CAP_INDICATORS", c.CapIndicators);
            Add("CAP_XFERCOUNT", c.CapXferCount);
            Add("CAP_SERIALNUMBER", c.CapSerialNumber);
            Add("ICAP_XFERMECH", c.ICapXferMech);
            Add("ICAP_IMAGEFILEFORMAT", c.ICapImageFileFormat);
            Add("ICAP_COMPRESSION", c.ICapCompression);
            Add("ICAP_UNITS", c.ICapUnits);
            Add("ICAP_PIXELTYPE", c.ICapPixelType);
            Add("ICAP_BITDEPTH", c.ICapBitDepth);
            Add("ICAP_XRESOLUTION", c.ICapXResolution);
            Add("ICAP_YRESOLUTION", c.ICapYResolution);
            Add("ICAP_XNATIVERESOLUTION", c.ICapXNativeResolution);
            Add("ICAP_YNATIVERESOLUTION", c.ICapYNativeResolution);
            Add("ICAP_PHYSICALWIDTH", c.ICapPhysicalWidth);
            Add("ICAP_PHYSICALHEIGHT", c.ICapPhysicalHeight);
            return list;
        }

        static string Describe<T>(IReadOnlyCapWrapper<T> cap)
        {
            try
            {
                if (!cap.IsSupported) return "not supported";
                var parts = new List<string>();
                if (cap.CanGetCurrent) parts.Add("current " + Text(cap.GetCurrent()));
                if (cap.CanGetDefault) parts.Add("default " + Text(cap.GetDefault()));
                if (cap.CanGet) parts.Add(Values(cap.GetValuesRaw()));
                parts.Add(cap.CanSet ? "settable" : "read-only");
                return string.Join("; ", parts);
            }
            catch (Exception ex)
            {
                return "error: " + ex.Message;
            }
        }

        static string Values(CapabilityReader raw)
        {
            switch (raw.ContainerType)
            {
                case ContainerType.Range:
                    return "range " + Text(raw.RangeMinValue) + " to " + Text(raw.RangeMaxValue) + ", step " + Text(raw.RangeStepSize) +
                           ", current " + Text(raw.RangeCurrentValue);
                case ContainerType.Enum:
                case ContainerType.Array:
                    return "values " + string.Join(", ", raw.CollectionValues.Cast<object>().Select(Text)) +
                           (raw.ContainerType == ContainerType.Enum ? " (current index " + raw.EnumCurrentIndex + ")" : "");
                case ContainerType.OneValue:
                    return "only " + Text(raw.OneValue);
                default:
                    return "container " + raw.ContainerType;
            }
        }

        /// <summary>
        /// Any capability by its number, through MSG_GET (read-only), including capabilities this tool
        /// has no wrapper for; null when the source refuses it.
        /// </summary>
        public string DescribeRaw(CapabilityId id)
        {
            try
            {
                using (var cap = new TWCapability(id))
                {
                    var rc = Source.DGControl.Capability.Get(cap);
                    if (rc != ReturnCode.Success) return null;
                    return Values(CapabilityReader.ReadValue(cap));
                }
            }
            catch (Exception ex)
            {
                return "error: " + ex.Message;
            }
        }

        /// <summary>The capabilities the source lists in CAP_SUPPORTEDCAPS, as numbers.</summary>
        public List<CapabilityId> SupportedCapabilityIds()
        {
            try { return Source.Capabilities.CapSupportedCaps.GetValues().ToList(); }
            catch (Exception) { return new List<CapabilityId>(); }
        }

        static string Text(object value)
        {
            switch (value)
            {
                case null: return "none";
                case TWFix32 fix: return ((float)fix).ToString("0.###", CultureInfo.InvariantCulture);
                case float f: return f.ToString("0.###", CultureInfo.InvariantCulture);
                case double d: return d.ToString("0.###", CultureInfo.InvariantCulture);
                default: return Convert.ToString(value, CultureInfo.InvariantCulture);
            }
        }

        /// <summary>
        /// Asks for native transfer of one 8-bit gray image at the given resolution, with no progress window.
        /// Each step reports the source's answer and the value it holds afterwards.
        /// </summary>
        public List<KeyValuePair<string, string>> Configure(int ppi)
        {
            var c = Source.Capabilities;
            var steps = new List<KeyValuePair<string, string>>();
            void Step<T>(string what, IReadOnlyCapWrapper<T> cap, Func<ReturnCode> set)
            {
                string result;
                if (!cap.IsSupported)
                {
                    result = "not supported";
                }
                else
                {
                    try
                    {
                        var rc = set();
                        result = rc == ReturnCode.Success ? "accepted" : "refused (rc=" + rc + ", condition=" + Source.GetStatus().ConditionCode + ")";
                    }
                    catch (Exception ex)
                    {
                        result = "error: " + ex.Message;
                    }
                    try { result += "; now " + Text(cap.GetCurrent()); } catch (Exception) { }
                }
                steps.Add(new KeyValuePair<string, string>(what, result));
            }

            Step("CAP_XFERCOUNT = 1", c.CapXferCount, () => c.CapXferCount.SetValue(1));
            Step("ICAP_XFERMECH = Native", c.ICapXferMech, () => c.ICapXferMech.SetValue(XferMech.Native));
            Step("CAP_INDICATORS = False", c.CapIndicators, () => c.CapIndicators.SetValue(BoolType.False));
            Step("ICAP_UNITS = Inches", c.ICapUnits, () => c.ICapUnits.SetValue(Unit.Inches));
            Step("ICAP_PIXELTYPE = Gray", c.ICapPixelType, () => c.ICapPixelType.SetValue(PixelType.Gray));
            Step("ICAP_XRESOLUTION = " + ppi, c.ICapXResolution, () => c.ICapXResolution.SetValue((TWFix32)(float)ppi));
            Step("ICAP_YRESOLUTION = " + ppi, c.ICapYResolution, () => c.ICapYResolution.SetValue((TWFix32)(float)ppi));
            return steps;
        }

        /// <summary>
        /// Returns every capability that <see cref="Configure"/> touches to the source's default (MSG_RESET),
        /// so a probe leaves no setting behind in drivers that remember their last values.
        /// </summary>
        public List<KeyValuePair<string, string>> ResetConfigured()
        {
            var c = Source.Capabilities;
            var steps = new List<KeyValuePair<string, string>>();
            void Reset<T>(string name, ICapWrapper<T> cap)
            {
                string result;
                try { result = !cap.IsSupported ? "not supported" : cap.CanReset ? cap.Reset().ToString() : "no reset"; }
                catch (Exception ex) { result = "error: " + ex.Message; }
                steps.Add(new KeyValuePair<string, string>(name, result));
            }
            Reset("CAP_XFERCOUNT", c.CapXferCount);
            Reset("ICAP_XFERMECH", c.ICapXferMech);
            Reset("CAP_INDICATORS", c.CapIndicators);
            Reset("ICAP_UNITS", c.ICapUnits);
            Reset("ICAP_PIXELTYPE", c.ICapPixelType);
            Reset("ICAP_XRESOLUTION", c.ICapXResolution);
            Reset("ICAP_YRESOLUTION", c.ICapYResolution);
            return steps;
        }

        /// <summary>The resolution the source currently holds, or NaN if it cannot say.</summary>
        public double CurrentResolution(bool horizontal)
        {
            try
            {
                var cap = horizontal ? Source.Capabilities.ICapXResolution : Source.Capabilities.ICapYResolution;
                return cap.IsSupported ? (float)cap.GetCurrent() : double.NaN;
            }
            catch (Exception)
            {
                return double.NaN;
            }
        }

        /// <summary>
        /// Enables the source without its dialog and waits for one image. The transfer starts no earlier
        /// than the settle time after enabling, as the Stage A helper found that this source needs it for
        /// a good image; messages keep flowing meanwhile.
        /// </summary>
        public CaptureOutcome Capture(TimeSpan settle, TimeSpan timeout) =>
            RunEnabled(SourceEnableMode.NoUI, settle, timeout);

        /// <summary>
        /// Shows the driver's own dialog (settings only if the source supports it) and waits until the
        /// researcher closes it; an image scanned from the dialog is returned for checking.
        /// </summary>
        public CaptureOutcome ShowDriverDialog(TimeSpan timeout)
        {
            bool uiOnly = false;
            try { uiOnly = Source.Capabilities.CapEnableDSUIOnly.IsSupported && Source.Capabilities.CapEnableDSUIOnly.GetCurrent() == BoolType.True; }
            catch (Exception) { }
            return RunEnabled(uiOnly ? SourceEnableMode.ShowUIOnly : SourceEnableMode.ShowUI, TimeSpan.Zero, timeout);
        }

        CaptureOutcome RunEnabled(SourceEnableMode mode, TimeSpan settle, TimeSpan timeout)
        {
            var session = _host.Session;
            var outcome = new CaptureOutcome();
            var clock = new Stopwatch();
            bool disabled = false;

            EventHandler<TransferReadyEventArgs> onReady = (s, e) =>
            {
                outcome.TransferReadyAfterMs = clock.ElapsedMilliseconds;
                var remaining = settle - clock.Elapsed;
                if (remaining > TimeSpan.Zero)
                {
                    outcome.SettleWaitMs = (long)remaining.TotalMilliseconds;
                    TwainHost.PumpFor(remaining);
                }
            };
            EventHandler<DataTransferredEventArgs> onData = (s, e) =>
            {
                try
                {
                    outcome.ImageInfo = e.ImageInfo;
                    using (var stream = e.GetNativeImageStream())
                    {
                        if (stream == null)
                        {
                            outcome.Error = "The source sent no image data.";
                            return;
                        }
                        using (var copy = new MemoryStream())
                        {
                            stream.CopyTo(copy);
                            outcome.Bmp = copy.ToArray();
                        }
                    }
                }
                catch (Exception ex)
                {
                    outcome.Error = "Reading the transferred image failed: " + ex.Message;
                }
            };
            EventHandler<TransferErrorEventArgs> onError = (s, e) =>
                outcome.Error = e.Exception != null
                    ? "Transfer error: " + e.Exception.Message
                    : "Transfer error (rc=" + e.ReturnCode + ", condition=" + e.SourceStatus?.ConditionCode + ").";
            EventHandler<TransferCanceledEventArgs> onCanceled = (s, e) => outcome.Error = "The source canceled the transfer.";
            EventHandler onDisabled = (s, e) => disabled = true;

            session.TransferReady += onReady;
            session.DataTransferred += onData;
            session.TransferError += onError;
            session.TransferCanceled += onCanceled;
            session.SourceDisabled += onDisabled;
            try
            {
                clock.Start();
                var rc = Source.Enable(mode, false, _host.WindowHandle);
                if (rc != ReturnCode.Success)
                {
                    outcome.Error = "Enabling the source failed (rc=" + rc + ", condition=" + Source.GetStatus().ConditionCode + ").";
                    return outcome;
                }
                if (!TwainHost.PumpUntil(() => disabled, timeout))
                {
                    if (outcome.Error == null) outcome.Error = "No image within " + timeout.TotalSeconds.ToString("0") + " s.";
                    session.ForceStepDown(4);
                }
                if (outcome.Bmp == null && outcome.Error == null)
                {
                    outcome.Error = "The source closed without sending an image.";
                }
                return outcome;
            }
            finally
            {
                outcome.TotalMs = clock.ElapsedMilliseconds;
                session.TransferReady -= onReady;
                session.DataTransferred -= onData;
                session.TransferError -= onError;
                session.TransferCanceled -= onCanceled;
                session.SourceDisabled -= onDisabled;
            }
        }

        /// <summary>Whether the source can hand over and take back its settings (CAP_CUSTOMDSDATA).</summary>
        public bool SupportsSettings()
        {
            try
            {
                var cap = Source.Capabilities.CapCustomDSData;
                return cap.IsSupported && cap.GetCurrent() == BoolType.True;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>The source's current settings (TWAIN custom DS data), or null if it keeps none.</summary>
        public byte[] ReadSettings() => Source.Settings;

        /// <summary>Applies saved settings and reports whether the source now returns the same bytes.</summary>
        public bool ApplySettings(byte[] settings)
        {
            Source.Settings = settings;
            var now = Source.Settings;
            return now != null && now.SequenceEqual(settings);
        }
    }
}
