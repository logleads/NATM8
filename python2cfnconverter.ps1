cd "C:\Users\pappg\Documents\NAT M8"

$code= Get-Content -Path  .\iprangegenerator.py 
$filename ="./cfncodeoutput.txt"
#.\temp.py

$modified='"'
for($i=0;$i -lt $code.Count;$i++)
{
    $line=$code[$i].replace('\','\\').Replace("`t","\t").Replace('"','\"')
    $newline=$line+' \n'
    #Write-Host $newline 
    $modified+=$newline   
}
$modified+='"'

Remove-Item -Path $filename
$modified | out-file -FilePath $filename

write-host "The python file has been converted to CFN JSON compatible string"
