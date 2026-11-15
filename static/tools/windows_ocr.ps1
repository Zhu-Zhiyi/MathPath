param([Parameter(Mandatory=$true)][string]$InputJson,[Parameter(Mandatory=$true)][string]$OutputJson)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
[void][Windows.Globalization.Language,Windows.Foundation,ContentType=WindowsRuntime]
[void][Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
[void][Windows.Storage.Streams.IRandomAccessStreamWithContentType,Windows.Storage.Streams,ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$taskMethod=([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 })[0]
function Await-Operation($Operation,[Type]$ResultType){$taskValue=$taskMethod.MakeGenericMethod($ResultType).Invoke($null,@($Operation));$taskValue.Wait();return $taskValue.Result}
$taskLanguage=[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Where-Object { $_.LanguageTag -like 'zh*' } | Select-Object -First 1
if($taskLanguage){$taskEngine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($taskLanguage)}else{$taskEngine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()}
$taskRows=@()
foreach($taskPath in (Get-Content -LiteralPath $InputJson -Raw -Encoding UTF8 | ConvertFrom-Json)){
 $taskStream=$null;$taskBitmap=$null
 try{
  if(!$taskEngine){throw 'No OCR language available'}
  $taskFile=Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync([string]$taskPath)) ([Windows.Storage.StorageFile])
  $taskStream=Await-Operation ($taskFile.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
  $taskDecoder=Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($taskStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $taskBitmap=Await-Operation ($taskDecoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $taskResult=Await-Operation ($taskEngine.RecognizeAsync($taskBitmap)) ([Windows.Media.Ocr.OcrResult])
  $taskRows+=@{path=[string]$taskPath;text=$taskResult.Text;language=$taskEngine.RecognizerLanguage.LanguageTag;status='ok'}
 }catch{$taskRows+=@{path=[string]$taskPath;text='';language='';status='unavailable'}}
 finally{if($taskBitmap){$taskBitmap.Dispose()};if($taskStream){$taskStream.Dispose()}}
}
[IO.File]::WriteAllText($OutputJson,(ConvertTo-Json -InputObject @($taskRows) -Depth 4),[Text.UTF8Encoding]::new($false))
