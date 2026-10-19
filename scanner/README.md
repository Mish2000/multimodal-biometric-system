# Scanner capture

The native OEM route implements H8 and was verified on the HiScan PRO. Run
these commands from the repository root in PowerShell. The scanner must be
connected and its existing Windows USB driver installed. Close other scanner
applications before capture.

Set `$driverDirectory` to the location of the supplied
`fx_hs_windows_10_driver_v3.3` folder. Keep its original files together. The
tool verifies the precise x86 runtime hashes; the x64 diagnostic package is
not interchangeable with it.

```powershell
$driverDirectory = '<path-to-fx_hs_windows_10_driver_v3.3>'
$scannerExe = '.\scanner\ScannerCapture\bin\Release\net48\ScannerCapture.exe'

# Build using the already restored, locked NTwain dependency.
dotnet build scanner/ScannerCapture -c Release --no-restore -p:RestoreLockedMode=true
& $scannerExe selftest

# Open the device and require a 1000-DPI readback; write a local report.
& $scannerExe oem-probe --driver-dir $driverDirectory

# Place the left index finger on the scanner. Capture and save automatically.
& $scannerExe oem-capture --driver-dir $driverDirectory --session live002 --finger 7 --attempts 3 --timeout-s 60

# Independently read back and check the accepted PNG files.
& $scannerExe check captures/live002
```

`--finger` uses the existing positions: 1-5 right thumb through little finger,
6-10 left thumb through little finger. Set it to the finger actually scanned.
`--attempts` is the number of accepted frames requested from that finger;
rejected frames do not count. No driver window, Enter key, or manual Save
operation is involved. The first frame may be discarded while the sensor
starts; hold the finger until the completion message.

Files are written under `captures/<session>/`. Each PNG has a JSON sidecar
containing its hash, timing, finger position, runtime fingerprint, acquisition
settings and all H7 check results. Rejected images and metadata go to
`captures/<session>/rejected/`. Timestamped names and exclusive image/metadata
creation preserve earlier attempts. Capture output is restricted to
`captures/`; probe reports to `local/`. Both are git-ignored. These prototype
files are unencrypted; do not treat this as the final system's sample store.

Optional native capture settings: `--settle-ms 1500`, `--initial-delay-s 0`,
`--out captures`. The automatic loop is bounded by `--timeout-s`; the parent
allows a further 15 seconds before terminating a stuck worker. Exit codes:
0 requested work completed, 1 invalid arguments, 2 runtime/device error or
watchdog timeout, 3 the requested accepted-frame count was not reached.

The older `probe`, `capture` and `save-settings` commands retain their TWAIN
behavior. They do not use the OEM route. See
[`docs/scanner-native-capture.md`](../docs/scanner-native-capture.md) for the
recovered ABI, binary evidence, tested call sequence and validation limits.
