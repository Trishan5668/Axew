; Custom NSIS hooks for AxewSetup.exe.
;
; These callbacks run during the standard NSIS template that electron-builder
; generates. They take care of two AXEW-specific concerns:
;
;   1. Create the per-user data directory ($APPDATA\Axew\models) where the
;      first-run Whisper model download will be cached. This way the model
;      manager never has to handle the "directory does not exist" edge case.
;
;   2. Refuse to overwrite an existing running AXEW install. Razorpay receipts
;      and the Whisper model are user data — we never want a corrupted partial
;      install to leave the user in a half-state.
;
; Verification-pending: testing on a clean Windows VM. Run:
;   pnpm --filter @axew/desktop make-installer
; then run the resulting AxewSetup.exe in a Windows Sandbox / clean VM.

!macro customInit
  ; If AXEW is already running we cannot replace its binary safely.
  FindWindow $0 "Chrome_WidgetWin_1" "Axew"
  ${If} $0 <> 0
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Axew is currently running. Please quit Axew before installing or updating."
    Abort
  ${EndIf}
!macroend

!macro customInstall
  ; Create the models cache directory so the first-run wizard finds it.
  CreateDirectory "$APPDATA\Axew"
  CreateDirectory "$APPDATA\Axew\models"
  CreateDirectory "$APPDATA\Axew\logs"
!macroend

!macro customUnInstall
  ; deleteAppDataOnUninstall is set to false in electron-builder.yml so the
  ; user's downloaded Whisper model survives a reinstall. If the user wants
  ; to fully wipe state they can delete %APPDATA%\Axew manually.
!macroend
