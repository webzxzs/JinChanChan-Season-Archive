$ErrorActionPreference = "Stop"
# 只负责把四份已核对结构的CSV导出为人类可读Excel；不读取网络/不作研究判断。
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$names = @('棋子','羁绊与效果','棋盘可能效果','赛季特色')
$out = Join-Path $root '金铲铲全赛季研究资料库.xlsx'
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.ScreenUpdating = $false
try {
    $book = $excel.Workbooks.Add()
    while ($book.Worksheets.Count -lt 4) { $null = $book.Worksheets.Add() }
    for ($i=0; $i -lt 4; $i++) {
        $name = $names[$i]
        $source = Join-Path $root ('tables\' + $name + '.csv')
        $sheet = $book.Worksheets.Item($i+1)
        $sheet.Name = $name
        $sheet.Activate()
        # Import-Csv 严格按CSV引号规则解析，避免Excel文本导入器误拆含引号的技能效果。
        $records = @(Import-Csv -LiteralPath $source -Encoding UTF8)
        if ($records.Count -eq 0) { throw "CSV无数据: $name" }
        $headers = @($records[0].PSObject.Properties.Name)
        $expected = @(21,11,11,10)[$i]
        if ($headers.Count -ne $expected) { throw "CSV字段数异常: $name ($($headers.Count) vs $expected)" }
        $matrix = [Array]::CreateInstance([object], [int[]]@(($records.Count+1), $headers.Count))
        for ($col=0; $col -lt $headers.Count; $col++) {
            $matrix.SetValue([string]$headers[$col],0,$col)
        }
        for ($row=0; $row -lt $records.Count; $row++) {
            for ($col=0; $col -lt $headers.Count; $col++) {
                $value = [string]$records[$row].PSObject.Properties[$headers[$col]].Value
                # 必须防止恶意或偶发的CSV首字符被Excel视为公式。
                if ($value.StartsWith('=')) { $value = "'" + $value }
                $isNumeric = (($i -eq 0) -and (($col+1) -in @(5,11,12,13,14,15,16,17))) -or (($i -eq 3) -and (($col+1) -in @(6,7)))
                $num = 0.0
                if ($isNumeric -and [double]::TryParse($value,[System.Globalization.NumberStyles]::Float,[System.Globalization.CultureInfo]::InvariantCulture,[ref]$num)) {
                    $matrix.SetValue($num,($row+1),$col)
                } else {
                    $matrix.SetValue($value,($row+1),$col)
                }
            }
        }
        $range = $sheet.Range($sheet.Cells.Item(1,1),$sheet.Cells.Item(($records.Count+1),$headers.Count))
        if ($range.Rows.Count -lt 2) { throw "$name 无数据，拒绝覆盖原有Excel" }
        # Excel某些环境不允许设置整个工作表的字体；只为已用数据区域设置。
        try { $range.Font.Name = 'Microsoft YaHei'; $range.Font.Size = 10 } catch { }
        try { $sheet.Range($sheet.Cells.Item(1,1),$sheet.Cells.Item(1,$headers.Count)).EntireColumn.ColumnWidth = 17 } catch { }
        $sheet.Columns.Item(1).ColumnWidth = 32
        $sheet.Columns.Item(2).ColumnWidth = 20
        $sheet.Rows.Item(1).RowHeight = 33
        $sheet.Rows.Item(1).WrapText = $true
        if ($i -eq 0) {
            $sheet.Columns.Item(9).ColumnWidth = 22
            $sheet.Columns.Item(10).ColumnWidth = 64
            $sheet.Columns.Item(10).WrapText = $true
            $sheet.Columns.Item(19).ColumnWidth = 39
            $sheet.Rows.Item('2:'+($records.Count+1)).RowHeight = 34
        }
        if ($i -eq 1) {
            $sheet.Columns.Item(5).ColumnWidth = 50
            $sheet.Columns.Item(6).ColumnWidth = 66
            $sheet.Columns.Item(7).ColumnWidth = 43
            $sheet.Columns.Item(5).WrapText = $true
            $sheet.Columns.Item(6).WrapText = $true
            $sheet.Rows.Item('2:'+($records.Count+1)).RowHeight = 42
        }
        if ($i -eq 2) {
            $sheet.Columns.Item(3).ColumnWidth = 29
            $sheet.Columns.Item(4).ColumnWidth = 27
            $sheet.Columns.Item(5).ColumnWidth = 64
            $sheet.Columns.Item(5).WrapText = $true
            $sheet.Rows.Item('2:'+($records.Count+1)).RowHeight = 45
        }
        if ($i -eq 3) {
            $sheet.Columns.Item(4).ColumnWidth = 63
            $sheet.Columns.Item(5).ColumnWidth = 38
            $sheet.Columns.Item(9).ColumnWidth = 42
            $sheet.Columns.Item(4).WrapText = $true
            $sheet.Rows.Item('2:'+($records.Count+1)).RowHeight = 42
        }
        $sheet.Columns.Item($headers.Count-1).ColumnWidth = 38
        $sheet.Activate()
        $excel.ActiveWindow.SplitRow = 1
        $excel.ActiveWindow.SplitColumn = 2
        $excel.ActiveWindow.FreezePanes = $true
        $range.Value2 = $matrix
        $table = $sheet.ListObjects.Add(1,$range,$null,1)
        $table.Name = @('Units','Traits','BoardEffects','SeasonFeatures')[$i]
        $table.TableStyle = 'TableStyleMedium2'
        Write-Output ("$name : " + ($range.Rows.Count-1) + " 条")
    }
    $book.Worksheets.Item(4).Activate()
    # SaveAs replacement affects only this generated research workbook.
    $book.SaveAs($out,51)
    Write-Output "Excel 已更新：$out"
    $book.Close($false)
}
finally {
    $excel.Quit()
}
