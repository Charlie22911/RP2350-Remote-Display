# Windows 11 guide

RP2350 Remote Display supports native USB hosting on 64-bit x86 Windows 11 (AMD64) with firmware and Python software from release 1.2.18 or later compatible versions. The firmware publishes Microsoft OS 2.0 descriptors, so Windows automatically associates the normal display interface with its inbox WinUSB driver. The Python package installs its packaged libusb backend dependency on Windows AMD64.

No Zadig step, project-specific INF, or separate libusb DLL download is required. The same firmware image and display protocol continue to work on Linux.

Windows ARM64 is not currently a supported native host because the packaged backend dependency is limited to AMD64. WSL 2 remains an alternative for running the Linux setup, but native Windows and WSL cannot own the same attached display at the same time.

## Choose a Windows host path

| Path | Use it when | USB owner |
|---|---|---|
| Native Windows (recommended) | Running the Python library, examples, or physical functional test directly from PowerShell | Windows through WinUSB |
| WSL 2 | Using the Linux bootstrap, Linux-only examples, or a Linux development environment | The selected WSL instance through `usbipd-win` |

BOOTSEL flashing is separate from both host paths. Windows mounts the board's ROM bootloader as a removable drive, regardless of which operating system will later run the host application.

## Flash compatible firmware

1. Obtain `rp2350_remote_display-1.2.18.uf2` and its matching `.uf2.sha2` checksum from release 1.2.18, or use later compatible firmware and host software from the same release. A locally built development artifact will not have a publisher-provided checksum. Firmware from 1.2.16 and earlier does not advertise WinUSB automatically.
2. In PowerShell, calculate the downloaded file's hash:

   ```powershell
   Get-FileHash .\rp2350_remote_display-1.2.18.uf2 -Algorithm SHA256
   ```

3. For a release download, compare the entire displayed hash with the published value. For a local development build, record the calculated hash with the test results.
4. Hold the board's BOOTSEL button while connecting or resetting it. Windows should mount a removable boot volume.
5. Copy the UF2 to that volume. The volume disconnects automatically when flashing completes and the board reboots into the normal display firmware.

BOOTSEL mode and normal display mode are different USB devices. A board showing `WAITING FOR HOST` has left BOOTSEL mode and is ready for a host application.

## Install the native Windows host

Clone or download the matching repository checkout, open PowerShell in its root directory, and create a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .\python
.\.venv\Scripts\python.exe -m pip check
```

The package installation brings in PyUSB, Pillow, and `libusb-package`. The `libusb-package` dependency supplies the libusb runtime that PyUSB uses with WinUSB; it does not replace the Windows device driver.

For a published release, install the downloaded wheel instead of the editable source directory:

```powershell
$wheel = Get-ChildItem .\rp2350_remote_display-*.whl | Select-Object -First 1
.\.venv\Scripts\python.exe -m pip install $wheel.FullName
```

Keep firmware and Python artifacts on matching project versions. Protocol 16 must match exactly even though the USB driver association happens before the display protocol starts.

## Verify the automatic WinUSB association

After flashing and reconnecting compatible firmware, open Device Manager and inspect the normal RP2350 Remote Display device:

1. Open the device's **Properties** dialog.
2. On the **Driver** page, confirm that Microsoft is the provider and that **Driver Details** lists `WinUSB.sys`.
3. If the board was attached to WSL, detach it before testing native access.

Do not manually replace the driver with Zadig or a custom INF. If Windows previously saw older firmware, flash the matching 1.2.18-line UF2, allow the board to reboot, and physically reconnect it so Windows enumerates the new descriptors.

The firmware's stable per-board USB serial supports deterministic selection when several displays are connected. The development USB identity is `CAFE:4010`; custom firmware may use another VID/PID, which the host application must select explicitly.

## Run an example natively

If `usbipd-win` is installed, check whether the display is currently attached to WSL:

```powershell
usbipd list
```

If the display is attached, detach its listed bus ID:

```powershell
usbipd detach --busid <BUSID>
```

Then run a hardware-independent import check and a display example:

```powershell
.\.venv\Scripts\python.exe -c "import rp2350_remote_display as rpd; print(rpd.__version__)"
.\.venv\Scripts\python.exe .\python\examples\basic_primitives.py
```

The board should leave `WAITING FOR HOST` and display the example scene. Most examples work on either supported host. `dirty_dashboard.py` is Linux-specific because it reads Linux system metrics, and `plasma_interactive.py` currently requires POSIX terminal controls.

## Run the physical functional test natively

The PowerShell runner creates or reuses `.venv-windows`, installs the package from this checkout, and checks that its version matches the repository. Run the hardware-independent preflight before the full physical test:

```powershell
.\functional-test\run.ps1 --preflight-only
.\functional-test\run.ps1 --report .\functional-test\reports\windows-native.json
```

Set `RPD_TEST_VENV` before invoking the runner if you want it to use another virtual-environment directory. The full test opens the board several times and includes interactive visual and touch stages. Close other applications using the display and keep it detached from WSL for the complete run. See the [testing guide](testing.md) for the validation classes and optional flags.

## Use the WSL 2 alternative

This path runs the Linux host software inside WSL 2. It requires a current WSL distribution and `usbipd-win`. Microsoft maintains the authoritative [WSL USB connection instructions](https://learn.microsoft.com/windows/wsl/connect-usb); follow them if command syntax differs from the summary below.

Install or update WSL and `usbipd-win`, then reboot if Windows requests it:

```powershell
wsl --install
winget install --interactive --exact dorssel.usbipd-win
```

Connect the board while it is running the normal display firmware. In an administrator PowerShell window, list USB devices and share the matching device once:

```powershell
usbipd list
usbipd bind --busid <BUSID>
```

Close every native application using the display. In PowerShell, attach the shared device to WSL 2:

```powershell
usbipd attach --wsl --busid <BUSID>
```

Inside WSL, confirm that the development USB identity is visible:

```bash
lsusb -d cafe:4010
```

Clone and prepare the host environment inside the WSL filesystem, not under `/mnt/c`, for predictable Linux permissions and performance:

```bash
git clone https://github.com/Charlie22911/RP2350-Remote-Display.git
cd RP2350-Remote-Display
./scripts/bootstrap-linux.sh --skip-firmware-build
```

After the udev group change, close all WSL shells, run `wsl --shutdown` from PowerShell, reopen WSL, reconnect or reattach the board, and verify `lsusb` again. Then run an example:

```bash
cd RP2350-Remote-Display
source .venv/bin/activate
python python/examples/basic_primitives.py
```

USB attachment is not persistent across every unplug, reset, or Windows restart. Run `usbipd list` and attach the current bus ID again when the device is no longer visible in WSL. Detach it before returning to native Windows:

```powershell
usbipd detach --busid <BUSID>
```

## Current boundaries

- Native hosting is supported on Windows 11 AMD64, not Windows ARM64.
- The Bash firmware build helpers and Linux bootstrap are documented for Linux or WSL; native Windows support covers flashing, the Python host, cross-platform examples, and the physical functional test.
- WinUSB association requires 1.2.18-line or later compatible firmware. Earlier firmware can still be used through Linux or WSL with its matching older host package, but it does not provide the supported native driver path.
- One process and one operating-system environment can own a display interface at a time.
- A custom firmware VID/PID must be passed to `RemoteDisplay.open()` or to the functional test's `--vid` and `--pid` options.
