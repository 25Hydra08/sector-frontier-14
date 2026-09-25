Param()
$png = "Tools\\lua\\Grid_Debugger\\icons\\iconGD512x512.png"
$ico = "Tools\\lua\\Grid_Debugger\\icons\\iconGD512x512.ico"
if (-not (Test-Path $png)) {
    Write-Error "PNG not found: $png"
    exit 1
}
Add-Type -AssemblyName System.Drawing
$bitmap = [System.Drawing.Bitmap]::FromFile($png)
$hIcon = $bitmap.GetHicon()
$icon = [System.Drawing.Icon]::FromHandle($hIcon)
$fs = [System.IO.File]::Open($ico, [System.IO.FileMode]::Create)
$icon.Save($fs)
$fs.Close()
Write-Output "ICO_CREATED: $ico"
