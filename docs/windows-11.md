# Windows 11 guide

Windows 11 support is currently split into two paths:

- **Firmware flashing:** supported through the board's native BOOTSEL mass-storage mode.
- **Python host application:** available as an experimental WSL 2 workflow using `usbipd-win` to forward the normal firmware USB device into Linux.

The project does not yet provide a supported native-Windows WinUSB driver setup. Windows CI runs hardware-independent Python tests plus package build and installation checks; it does not validate a physical board.

## Flash a release UF2 from Windows

1. Download the firmware UF2 and its checksum file from the [GitHub releases page](https://github.com/Charlie22911/RP2350-Remote-Display/releases).
2. In PowerShell, calculate the downloaded UF2 hash:

   ```powershell
   Get-FileHash .\rp2350_remote_display.uf2 -Algorithm SHA256
   ```

3. Compare the displayed hash with the SHA-256 value published beside that release.
4. Hold the board's BOOTSEL button while connecting or resetting it. Windows should mount a removable boot volume.
5. Copy the UF2 to that volume. The volume disconnects automatically when flashing completes and the board reboots into the normal display firmware.

The normal firmware USB interface is different from the BOOTSEL mass-storage device. A board showing `WAITING FOR HOST` has left BOOTSEL mode successfully.

## Run the host through WSL 2

This route keeps the project's Linux setup and libusb behavior while using a Windows 11 computer. It requires a current WSL 2 distribution and `usbipd-win`. Microsoft maintains the authoritative [WSL USB connection instructions](https://learn.microsoft.com/windows/wsl/connect-usb); follow them if command syntax differs from the summary below.

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

In PowerShell, attach the shared device to WSL 2:

```powershell
usbipd attach --wsl --busid <BUSID>
```

The attachment is not tied to that PowerShell window. Inside WSL, confirm that the development USB identity is visible:

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

USB attachment is not persistent across every unplug, reset, or Windows restart. Run `usbipd list` and `usbipd attach --wsl --busid <BUSID>` again when the device is no longer visible in WSL. Detach it explicitly when needed:

```powershell
usbipd detach --busid <BUSID>
```

## Native-Windows limitation

The normal firmware presents a vendor-specific USB bulk interface. It does not currently publish Microsoft OS descriptors that automatically associate it with WinUSB, and the project does not install or validate a native libusb backend. A manual driver association can alter which Windows driver owns the device and is outside the supported setup.

Native Windows host support should add and test all of the following together:

- Microsoft OS 2.0 descriptors and an explicit device-interface identity.
- A documented PyUSB/libusb backend installation and removal path.
- Validation of the existing stable per-board USB serial and deterministic
  multi-device selection through that native backend.
- Physical connection, reconnect, error-recovery, and multiple-board tests on Windows.

Until that work is complete, use native Windows only for BOOTSEL flashing and use WSL 2 for the Python host application.
