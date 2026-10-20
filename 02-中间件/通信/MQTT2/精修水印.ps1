Add-Type -AssemblyName System.Drawing
$root = 'D:\WTSD\embedded-engineering-notes\02-中间件\通信\MQTT2'
$navy = [Drawing.Color]::FromArgb(255, 9, 37, 62)
$fontFamily = New-Object Drawing.FontFamily('楷体')
$titleSize = 64.0
$titles = @('章节总览','温湿度上报与水泵下控','Topic 怎样找到订阅者','从建立连接到收到命令','两个客户端跑通双向通信','QoS 0、1、2 的交付边界','从协议确认到执行完成','Retain、持久会话与遗嘱','断网后的检测与恢复','MQTT 消息如何进入控制任务','安全配置与分层排障','多设备扩展与边缘联动')
$boxes = @(@(765,398,150,38),@(758,446,164,42),@(750,546,175,44),@(772,468,145,39),@(772,452,145,36),@(736,442,202,50),@(758,276,163,40),@(832,446,141,39),@(723,438,104,32),@(749,397,181,47),@(765,451,155,39),@(750,447,180,44))
$backgroundSamples = @(@(950,420),@(940,470),@(930,560),@(950,490),@(530,540),@(840,495),@(740,292),@(980,465),@(720,450),@(990,420),@(940,465),@(1000,470))
function Draw-TextPath($graphics, $value, [single]$size, [single]$x, [single]$y, $color, [bool]$center) {
    $path = New-Object Drawing.Drawing2D.GraphicsPath
    $path.AddString($value, $fontFamily, 0, $size, [Drawing.PointF]::new(0,0), [Drawing.StringFormat]::GenericTypographic)
    $bounds = $path.GetBounds()
    $matrix = New-Object Drawing.Drawing2D.Matrix
    if ($center) { $matrix.Translate($x-$bounds.X-$bounds.Width/2, $y-$bounds.Y-$bounds.Height/2) }
    else { $matrix.Translate($x-$bounds.X, $y-$bounds.Y) }
    $path.Transform($matrix)
    $brush = [Drawing.SolidBrush]::new($color)
    $graphics.FillPath($brush, $path)
    $brush.Dispose(); $matrix.Dispose(); $path.Dispose()
}
foreach ($index in 1..12) {
    $file = Get-ChildItem -LiteralPath $root -Filter "$index-*.png" | Select-Object -First 1
    $loaded = [Drawing.Bitmap]::new($file.FullName)
    $bitmap = [Drawing.Bitmap]::new($loaded.Width,$loaded.Height,[Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $graphics.DrawImageUnscaled($loaded,0,0)
    $loaded.Dispose()
    $graphics.Dispose()
    $original = $bitmap.Clone()
    $box = $boxes[$index-1]
    $samplePoint = $backgroundSamples[$index-1]
    $cleanColor = $original.GetPixel($samplePoint[0],$samplePoint[1])
    $removed = 0
    for ($y=$box[1]; $y -lt $box[1]+$box[3]; $y++) {
        for ($x=$box[0]; $x -lt $box[0]+$box[2]; $x++) {
            $pixel = $original.GetPixel($x,$y)
            $minimum = [Math]::Min($pixel.R,[Math]::Min($pixel.G,$pixel.B))
            $maximum = [Math]::Max($pixel.R,[Math]::Max($pixel.G,$pixel.B))
            if ($minimum -gt 145 -and $maximum-$minimum -le 35) {
                $bitmap.SetPixel($x,$y,$cleanColor); $removed++
                continue
                $found = $false
                for ($radius=1; $radius -le 24 -and -not $found; $radius++) {
                    foreach ($direction in @(@(0,-1),@(0,1),@(-1,0),@(1,0))) {
                        $sx=$x+$radius*$direction[0]; $sy=$y+$radius*$direction[1]
                        $candidate=$original.GetPixel($sx,$sy)
                        if ($candidate.R -gt 240 -and $candidate.G -gt 238 -and $candidate.B -gt 231) {
                            $bitmap.SetPixel($x,$y,$candidate); $found=$true; $removed++; break
                        }
                    }
                }
            }
        }
    }
    $original.Dispose()
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $paper = $bitmap.GetPixel(10,10)
    $paperBrush = [Drawing.SolidBrush]::new($paper)
    $graphics.FillRectangle($paperBrush,0,0,$bitmap.Width,116)
    if ($index -eq 1) { $graphics.FillRectangle($paperBrush,550,112,600,14) }
    if ($index -eq 11) { $graphics.FillRectangle($paperBrush,16,110,145,43); $graphics.FillRectangle($paperBrush,165,116,810,15) }
    $cardBrush = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(250,218,147))
    $cardPen = [Drawing.Pen]::new($navy,3)
    $cardPath=New-Object Drawing.Drawing2D.GraphicsPath
    $cardPath.AddArc(36,18,20,20,180,90); $cardPath.AddArc(121,18,20,20,270,90)
    $cardPath.AddArc(121,84,20,20,0,90); $cardPath.AddArc(36,84,20,20,90,90); $cardPath.CloseFigure()
    $graphics.FillPath($cardBrush,$cardPath); $graphics.DrawPath($cardPen,$cardPath)
    Draw-TextPath $graphics "$index" 64 88.5 61 $navy $true
    Draw-TextPath $graphics $titles[$index-1] $titleSize 172 28 $navy $false
    if ($index -eq 9) {
        $patchColor=$bitmap.GetPixel(900,136)
        $patchBrush=[Drawing.SolidBrush]::new($patchColor)
        $graphics.FillRectangle($patchBrush,626,138,276,105)
        $lines=@('Broker 超过约90秒','未收到客户端','MQTT 控制报文，','则断开连接')
        for ($line=0; $line -lt 4; $line++) { Draw-TextPath $graphics $lines[$line] 26 633 (141+$line*25) $navy $false }
        $patchBrush.Dispose()
    }
    Draw-TextPath $graphics 'code闲录' ($titleSize/2) ($bitmap.Width/2) ($bitmap.Height/2) ([Drawing.Color]::FromArgb(89,204,204,204)) $true
    $graphics.Dispose(); $paperBrush.Dispose(); $cardBrush.Dispose(); $cardPen.Dispose(); $cardPath.Dispose()
    $temporary=Join-Path $root '修订记录\精修暂存.png'
    $bitmap.Save($temporary,[Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    Copy-Item -LiteralPath $temporary -Destination $file.FullName -Force
    Write-Output "$index watermark_pixels_cleaned=$removed RGB font=楷体 title=64px watermark=32px center=(836,470.5) alpha=89/255"
}
$fontFamily.Dispose()
