# SCript logic:
# I)   Get variables 1)region, 2)VPC id, 3)vpc cidr,4)subnets,5)route tables,6) ASG properties. 
# II)  Associate subnets with route tables, only after boot time.
# III) Modify Route tables in one of the 3 scenarios:
#      a) 1 Nat instance N (all) subnets 
#      b) 1 Nat instance 1 subnet, the instance takes over remote subnets if no instance exisits in the remote subnet    
#      c) M Nat instance N subnet, example 2 NAT, 3 Subnet  , the instance takes over remote subnets as soon as the route is blackhole
# IV) Scaling up if CPU usage in given timeframe is over a predefined percentage (and ASG is not at max), settings are provided in CloudFormation form
# V)  Scale down if Network troughput (IN+OUT traffic) is lower than predefined megabyte, settings are provided in CloudFormation form
#      a) Mark all other instances protected from scale in 
#      b) Before sale in check if another instance exists if yes set default route (of the local subnet) to that instance
#      c) Implement a file based counter afer checking ASG if protected enabled increment counter. If not than check if file exists if exists delete it. 

function Set-DefaultRoute {
    param (
        $privateroutetables,
        $subnet,
        $AZ_NAME,
        $ENI_ID,
        $INSTANCE_ID,
        $REGION,
        $logfrequency
    )
        $localroutetable=$($privateroutetables|where-object { $_.Associations.GetEnumerator() | ? { $_.SubnetId -eq  $subnet.SubnetId } })
        $SameEniSet=$($($localroutetable.Routes|Where-Object {$_.NetworkInterfaceId -eq $ENI_ID})-ne $null)

        #check here if default route exists if not create it 
        if ($($localroutetable| Where-Object {$_.Routes.DestinationCidrBlock -contains "0.0.0.0/0"}) -eq $null){
            invoke-expression "aws ec2 create-route --route-table-id  $($localroutetable.RouteTableId) --destination-cidr-block 0.0.0.0/0 --network-interface-id $ENI_ID --region $REGION"
            write-host "Creating Default route for $($subnet.SubnetId) to $ENI_ID (instance: $INSTANCE_ID)`n"
            
        }
        elseif($SameEniSet){

             if (($($(get-date).Minute % $logfrequency) -eq 0) ){
                write-host "RoutetableId $($localroutetable.RouteTableId) (attached to $($subnet.SubnetId)) already has Default route for set to $ENI_ID (instance: $INSTANCE_ID).`n"
             } 
        }
        else {
        #if default route exists but not the desired value, instance that is no longer available, instance that is available but not local to the subnet etc, then update default route.
            invoke-expression "aws ec2 replace-route --route-table-id  $($localroutetable.RouteTableId) --destination-cidr-block 0.0.0.0/0 --network-interface-id $ENI_ID --region $REGION"
            write-host "Updating Default route for $($subnet.SubnetId) to $ENI_ID (instance: $INSTANCE_ID)`n"
        }

}

function Set-Association-SubnetsRouteTables{
    param (
        $privateroutetables,
        $privatesubnetobjects,
        $route_tables,
        $REGION
    )

    #Associate subnets desginated as private in the Cloudformation Template with RouteTables created in CloudFormation.
    for ($i = 0; $i -lt $privatesubnetobjects.Count; $i++){

     $subnet=$privatesubnetobjects[$i]
     $oneprivateroutetable=$privateroutetables |where-Object {$_.Tags.GetEnumerator() | ? { $_.Value -eq "RouteTable"+$($i+1) }}
     $currentlyconfiguredroutetable=$($route_tables | where-Object {$_.Associations.SubnetId -contains $subnet.SubnetId })
 
        #Validate Route table subnet association, each private subnet must be 1 to 1 mapped with a route table.  
        if ( $privateroutetables.RouteTableId -notcontains $currentlyconfiguredroutetable.RouteTableId ) {
        # The currently associate route table is not in the privatesubnetlist. 
        
            Write-Host "Disassociating route $($currentlyconfiguredroutetable.RouteTableId) from $($subnet.SubnetId)"
            $associationid=$($currentlyconfiguredroutetable.Associations |where-Object {$_.SubnetId -eq $subnet.SubnetId}).RouteTableAssociationId

            invoke-expression "aws ec2 disassociate-route-table --region $REGION --association-id $associationid --output json"
        
            #Associate routetable
            invoke-expression "aws ec2 associate-route-table --region $REGION --route-table-id  $($oneprivateroutetable.RouteTableId) --subnet-id  $($subnet.SubnetId) --output json"
            write-host  "Associating route $($oneprivateroutetable.RouteTableId) with $($subnet.SubnetId)"
        }else{
            write-host "Routetable  $($oneprivateroutetable.RouteTableId) association (to $($subnet.SubnetId)) is correct"
        }
    }

}

function Test-RemoteSubnet-DefaultRoute{

    param (
        $remotesubnets,
        $privateroutetables,
        $autoscalinggroup,
        $AZ_NAME,
        $ENI_ID,
        $INSTANCE_ID,
        $REGION,
        $checkinstances,
        $logfrequency
    )

     for ($j = 0; $j -lt $remotesubnets.Count; $j++){
            $oneremotesubnet=$remotesubnets[$j]
            $oneremoteroutetable=$privateroutetables | where-object {$_.Associations |where-Object {$_.SubnetId -eq $oneremotesubnet.SubnetId} }

            $missingdefaultroute=$($($oneremoteroutetable.Routes | Where-Object {$_.DestinationCidrBlock -contains "0.0.0.0/0"}) -eq $null) 
            $failedroutes=$($($oneremoteroutetable| Where-Object {$_.DestinationCidrBlock -contains "0.0.0.0/0"}| Where-Object {$_.Routes.State -contains "blackhole"}) -ne $null)
            
            if($checkinstances -eq $true){
                $samezoneinstanceexists=$($($autoscalinggroup.Instances | Where-Object {$_.AvailabilityZone -eq $remotesubnets[$j].AvailabilityZone}) -ne $null)
                #TODO enhance with historical data using a file based counter. if its failed (blackhole for eg.:5 minutes) than set variable to false 
            }
            else{
                $samezoneinstanceexists=$false
            }

            #if the remote subnet does not have a working default route and there is no instance in the same zone
            if(($missingdefaultroute -or $failedroutes) -and ($samezoneinstanceexists -eq $false)){
                Set-DefaultRoute -subnet $oneremotesubnet -privateroutetables $privateroutetables -AZ_NAME $AZ_NAME -ENI_ID $ENI_ID -INSTANCE_ID $INSTANCE_ID -REGION $REGION -logfrequency $logfrequency
                write-host "Setting remote $($oneremotesubnet.SubnetId) default route to $INSTANCE_ID $ENI_ID"
                start-sleep -Seconds 1 
            }
            else {
                write-host "Validates remote $($oneremotesubnet.SubnetId) routetable $( $oneremoteroutetable.RouteTableId) is configured correctly"
            }
     }        

}

function Test-first-run{
    #create flag/file, to enable post system boot subnet association confgiuration   
    $filepath="/tmp/BOOT_TIME"
    $firstboot=Test-path ($filepath)

    if ($firstboot -eq $false){
        New-Item $filepath
        Set-Content $filepath $(Get-Date)
        #First execution
        $result=$true
    }
    else {
        #Consequent execution
        $result=$false
    }

    return $result   
}

function Compare-CWMetrics-ASGScalingThresholds{
    param (
        $REGION,
        $INSTANCE_ID,
        $AZ_NAME,
        $ScaleConfig,
        $autoscalinggroup,
        $privatesubnetobjects,
        $logfrequency
    )

    $currentinstance=$autoscalinggroup.Instances | Where-Object {$_.InstanceId -eq $INSTANCE_ID}
    $isASGatMinimum=$autoscalinggroup.MinSize -ge $($autoscalinggroup.Instances | Measure-Object).Count
    $isASGatMaximum=$autoscalinggroup.MaxSize -lt $($autoscalinggroup.Instances | Measure-Object).Count
    $localsubnet=$privatesubnetobjects | where-object {$_.AvailabilityZone -eq $AZ_NAME}
    $boottime=$(Get-Content /tmp/BOOT_TIME |Get-date)

    #Get current Metrics
    $start_time=$(date --utc -d "24 hours ago" '+%Y-%m-%dT%H:%M:%S')
    $now=$(date '+%Y-%m-%dT%H:%M:%S')
    $MetricDataResults=$(invoke-expression "aws cloudwatch get-metric-data --cli-input-json file:///tmp/cwconfig.json --region $REGION --start-time $start_time --end-time $now"|ConvertFrom-Json).MetricDataResults
   
    if (($ScaleConfig.ScaleUPConfig -ne $null) -and ($(Get-Date).AddMinutes(-10) -gt $boottime)){
        #determine if scale up threshold reached and scale up is possible if both yes than scale up.
        $CPUUtilization=Convert-CW-Metrics -Metrics $($MetricDataResults| where-object { $_.Label -eq "CPUUtilization"}) |Sort-Object Date -Descending
        $timeoflatestdata=get-date $CPUUtilization[0].Date
        $timeoffirstrelevantdata=$timeoflatestdata.ToUniversalTime().AddMinutes(-$ScaleConfig.ScaleUPConfig.TimePeriod)
        $relevantmetrics= $CPUUtilization |Where-object {$_.Date -ge $timeoffirstrelevantdata} 
        $utilisation=$relevantmetrics | Measure-Object -Property Value -Average -Sum -Maximum -Minimum
       
        $showutilisationdata=$false

        if (($utilisation.Average -ge $ScaleConfig.ScaleUPConfig.CpuThreshold) -and $isASGatMaximum){
            $showutilisationdata=$true
            write-host "CPU utilisation is over the configured threshold of $($ScaleConfig.ScaleUPConfig.CpuThreshold)%, but no instance can be launched as ASG is already at Maximum.`nConsider bigger instances or relocating instances to other AZs."    

        }
        elseif($utilisation.Average -ge $ScaleConfig.ScaleUPConfig.CpuThreshold) {
            $showutilisationdata=$true
            write-host "CPU utilisation is over the configured threshold of $($ScaleConfig.ScaleUPConfig.CpuThreshold)%, and ASG is not at the maximum hence launching a new instance to share the load"
            invoke-expression "aws autoscaling set-desired-capacity --auto-scaling-group-name $($autoscalinggroup.AutoScalingGroupARN.split("/")[1]) --desired-capacity $($autoscalinggroup.DesiredCapacity+1) --honor-cooldown --region $REGION"
            
        }
        else {
            write-host "."
            if ($(get-date).Minute % $logfrequency -eq 0){
               write-host "CPU utilisation is under the configured threshold of $($ScaleConfig.ScaleUPConfig.CpuThreshold)%, no up scaling need to happen." 
            } 
   
        } 


        if (($(get-date).Minute % $logfrequency -eq 0) -or $showutilisationdata){
            #write usage statistics to log every x minutes or when there is a scaling action
            write-host "CPU utilisation data:`n" $relevantmetrics 
        } 

    }

    if (($ScaleConfig.ScaleDownConfig -ne $null) -and ($(Get-Date).AddMinutes(-10) -gt $boottime)){

        #determine if scale down threshold reached and scale down is possible if both yes than scale down
        if ($isASGatMinimum -ne $true){

            $NetworkIn=Convert-CW-Metrics -Metrics $($MetricDataResults| where-object { $_.Label -eq "networkIn"}) |Sort-Object Date -Descending
            $NetworkOut=Convert-CW-Metrics -Metrics $($MetricDataResults| where-object { $_.Label -eq "networkOut"}) |Sort-Object Date -Descending
        
            $timeoflatestdata=get-date $NetworkIn[0].Date
            $timeoffirstrelevantdata=$timeoflatestdata.ToUniversalTime().AddMinutes(-$ScaleConfig.ScaleDownConfig.TimePeriod)
            
            $relevantmetricsNI= $NetworkIn |Where-object {$_.Date -ge $timeoffirstrelevantdata} 
            $relevantmetricsNO= $NetworkOut |Where-object {$_.Date -ge $timeoffirstrelevantdata} 
            $utilisationNIKB=[math]::ceiling($($relevantmetricsNI | Measure-Object -Property Value -Average -Sum -Maximum -Minimum).Sum /1024)
            $utilisationNOKB=[math]::ceiling($($relevantmetricsNO | Measure-Object -Property Value -Average -Sum -Maximum -Minimum).Sum /1024)
            $combinedutilisation=$($utilisationNIKB+$utilisationNOKB)

    
            if (   ($ScaleConfig.ScaleDownConfig.NetworkThreshold *1024) -gt $combinedutilisation ){ #TODO COMPARE here for boot time
               
               write-host "Current instance $($INSTANCE_ID) had  combined in and out traffic of $([Math]::Round($($combinedutilisation/1024),3)) MB in $($ScaleConfig.ScaleDownConfig.TimePeriod) minute period,scale down imminent as the minimum limit is $($ScaleConfig.ScaleDownConfig.NetworkThreshold) MB"    
               
               if ($autoscalinggroup.Instances.Count -gt 1){

                   #set instance protection on other instances to avoid 
                   $allotherinstances=$autoscalinggroup.Instances | Where-Object {$_.InstanceId -ne $INSTANCE_ID}
                   $allotherinstancids=$allotherinstances| % {$_.InstanceId}
                   Invoke-Expression "aws autoscaling  set-instance-protection --protected-from-scale-in --instance-ids  $($allotherinstancids -join ",") --auto-scaling-group-name $($autoscalinggroup.AutoScalingGroupARN.split("/")[1]) --region $REGION"

                   #gracefully handover route to another instance, to minimuse the downtime.
                   $Ec2InstanceDetails=$(Invoke-Expression "aws ec2 describe-instances --instance-ids $($allotherinstancids -join ",") --region $REGION"|ConvertFrom-Json).Reservations
                   #to ensure that results are present.
                   start-sleep -Seconds 2
                   Set-DefaultRoute -subnet  $localsubnet.SubnetId -privateroutetables $privateroutetables -AZ_NAME $Ec2InstanceDetails.Instances[0].Placement.AvailabilityZone `
                                        -ENI_ID $Ec2InstanceDetails.Instances[0].NetworkInterfaces.NetworkInterfaceId -INSTANCE_ID $Ec2InstanceDetails.Instances[0].InstanceId -REGION $REGION -logfrequency $logfrequency

                   write-host "Setting localsubnet $( $localsubnet.SubnetId) default route to $($allotherinstancids[0]) $($Ec2InstanceDetails.Instances[0].NetworkInterfaces.NetworkInterfaceId)"

                   Start-Sleep -Seconds 5
               }
               
               invoke-expression "aws autoscaling set-desired-capacity --auto-scaling-group-name $($autoscalinggroup.AutoScalingGroupARN.split("/")[1]) --desired-capacity $($autoscalinggroup.DesiredCapacity-1) --honor-cooldown --region $REGION"
            }
            else{

                 if ($($(get-date).Minute % $logfrequency) -eq 0){
                    #Usage statistics to log every x minutes
                    write-host "Current instance $($INSTANCE_ID) had  combined in and out traffic of $([Math]::Round($($combinedutilisation/1024),3))  MB in $($ScaleConfig.ScaleDownConfig.TimePeriod) minute period, no down scaling action will take place as the limit is $($ScaleConfig.ScaleDownConfig.NetworkThreshold) MB"  
                 } 
            }


        }
        else {
            write-host "AutoScaling group minimum instance size reached no further scale down is possible."    
        } 

       
    }
    
    #TODO handle case of CW data is not available for X minutes,using Set-StateofEnvironment function 
}

function Set-CW-Metrics-Config{
    param (
        $REGION,
        $INSTANCE_ID
    )
    #Create config file to be used in Compare-CWMetrics-ASGScalingThresholds function.

    $cwconfigfile=@"
{
"MetricDataQueries": [{
		"Id": "cpuUtilization",
		"MetricStat": {
			"Metric": {
				"Namespace": "AWS/EC2",
				"MetricName": "CPUUtilization",
				"Dimensions": [{
					"Name": "InstanceId",
					"Value": "$($INSTANCE_ID)"
				}]
			},
			"Period": 60,
			"Stat": "Average"
		},
		"ReturnData": true
	},
	{
		"Id": "networkOut",
		"MetricStat": {
			"Metric": {
				"Namespace": "AWS/EC2",
				"MetricName": "NetworkOut",
				"Dimensions": [{
					"Name": "InstanceId",
					"Value": "$($INSTANCE_ID)"
				}]
			},
			"Period": 60,
			"Stat": "Average"
		},
		"ReturnData": true
	},
	{
		"Id": "networkIn",
		"MetricStat": {
			"Metric": {
				"Namespace": "AWS/EC2",
				"MetricName": "NetworkIn",
				"Dimensions": [{
					"Name": "InstanceId",
					"Value": "$($INSTANCE_ID)"
				}]
			},
			"Period": 60,
			"Stat": "Average"
		},
		"ReturnData": true
	}

]
}
"@

    $cwconfigfile | Out-File /tmp/cwconfig.json
    write-host "Cloudwatch Metrics Configuration file set"
    
    #Start-Sleep -Seconds 5
    #invoke-expression "systemctl start amazon-cloudwatch-agent"
    #write-host "Cloudwatch Agent started"

}

function Convert-CW-Metrics{
     param (
        $Metrics
    )

    $result=@()
    
     for ($l = 0; $l -lt $Metrics.Timestamps.Count; $l++){

         $date=$(get-date $Metrics.Timestamps[$l]).ToUniversalTime()
         $value=$Metrics.Values[$l]

         $converted = New-Object PSObject
         Add-Member -InputObject $converted -MemberType NoteProperty -Name Date -Value $date
         Add-Member -InputObject $converted -MemberType NoteProperty -Name Value -Value $value

         $result+=$converted
     }

     return $result
}

function Get-ASG-ScalingConfig{
    param (
        $TAGS
    )
    
    try{
        $ScaleUPConfig=$($($TAGS|ConvertFrom-Json).Tags|Where-Object {$_.key -eq "ScaleUPConfig"}).Value |ConvertFrom-Json
    }
    catch{
        $ScaleUPConfig=$null
    }


    try{
        $ScaleDownConfig=$($($TAGS|ConvertFrom-Json).Tags|Where-Object {$_.key -eq "ScaleDownConfig"}).Value |ConvertFrom-Json
    }
    catch{
        $ScaleDownConfig=$null
    }

    $Scaleconfig = New-Object PSObject

    Add-Member -InputObject $Scaleconfig -MemberType NoteProperty -Name ScaleUPConfig -Value $ScaleUPConfig
    Add-Member -InputObject $Scaleconfig -MemberType NoteProperty -Name ScaleDownConfig -Value $ScaleDownConfig

    return $Scaleconfig
}

function Set-StateofEnvironment{
    param (
        $counterpath
    )
    # The function increments a  file based counter (flag) that reflects environment state, such as if ASG scale in protection is enabled, +1 file. 
    # Runs at every execution, once threshold reached necessary action is taken. 

    $counterpath = "/tmp/ASGscaleinprotection"
    if($(test-path $counterpath )-eq $false){
    
        New-Item -Path $counterpath -Value "0"
    }else{
        [int]$data = Get-Content $counterpath
        $data+1 | out-file $counterpath -Force
    }

}

function Mange-routes{
    param (
        $autoscalinggroup,
        $privatesubnetobjects,
        $privateroutetables,
        $logfrequency,
        $AZ_NAME,
        $ENI_ID,
        $INSTANCE_ID,
        $REGION
    )

    #Add or update routes in RouteTables, depending on the Scenario.
    for ($j = 0; $j -lt $autoscalinggroup.Instances.InstanceId.Count; $j++){
 
        #$autoscalinggroup.Instances[$j]

        if ($autoscalinggroup.Instances.InstanceId.Count -eq 1){
            write-host "1 router-N subnet Scenario"
            #1-N Scenario
            for ($k = 0; $k -lt $privatesubnetobjects.Count; $k++){
                $onesubnet=$privatesubnetobjects[$k]
                Set-DefaultRoute -subnet $onesubnet -privateroutetables $privateroutetables -AZ_NAME $AZ_NAME -ENI_ID $ENI_ID -INSTANCE_ID $INSTANCE_ID -REGION $REGION -logfrequency $logfrequency 
                #to avoid rate limitting
                start-sleep -Seconds 1 
            }
        }
        elseif($autoscalinggroup.Instances.InstanceId.Count -eq $privatesubnetobjects.count){
            write-host "1 router -1 subnet Scenario"
            #1-1 Scenario
            $localsubnet=$privatesubnetobjects | where-object {$_.AvailabilityZone -eq $AZ_NAME}
            $remotesubnets=$privatesubnetobjects | where-object {$_.AvailabilityZone -ne $AZ_NAME}
            Set-DefaultRoute -subnet $localsubnet -privateroutetables $privateroutetables -AZ_NAME $AZ_NAME -ENI_ID $ENI_ID -INSTANCE_ID $INSTANCE_ID -REGION $REGION -logfrequency $logfrequency 
        
            Test-RemoteSubnet-DefaultRoute -remotesubnets $remotesubnets -privateroutetables $privateroutetables -autoscalinggroup $autoscalinggroup `
            -AZ_NAME $AZ_NAME -ENI_ID $ENI_ID -INSTANCE_ID $INSTANCE_ID -REGION $REGION -checkinstances $true

        }
        else{
            write-host "N router -M subnet Scenario"
            #N-M Scenario
            $localsubnet=$privatesubnetobjects | where-object {$_.AvailabilityZone -eq $AZ_NAME}
            $remotesubnets=$privatesubnetobjects | where-object {$_.AvailabilityZone -ne $AZ_NAME}
            Set-DefaultRoute -subnet $localsubnet -privateroutetables $privateroutetables -AZ_NAME $AZ_NAME -ENI_ID $ENI_ID -INSTANCE_ID $INSTANCE_ID -REGION $REGION  -logfrequency $logfrequency 
        
            Test-RemoteSubnet-DefaultRoute -remotesubnets $remotesubnets -privateroutetables $privateroutetables -autoscalinggroup $autoscalinggroup `
            -AZ_NAME $AZ_NAME -ENI_ID $ENI_ID -INSTANCE_ID $INSTANCE_ID -REGION $REGION -checkinstances $false
        }
}


}
         

#----------------------------------------------
$VPC_CIDR=Get-Content /tmp/VPC_CIDR
$VPC_ID=Get-Content /tmp/VPC_ID
$REGION= Get-Content /tmp/REGION
$STACKNAME= Get-Content /tmp/STACKNAME
$ALL_SUBNETS_LIST = Get-Content /tmp/ALL_SUBNETS_LIST
$INSTANCE_ID= Get-Content /tmp/INSTANCEID
$TAGS=Get-Content /tmp/TAGS
$AZ_NAME= Get-Content /tmp/AZ_NAME
$ENI_ID = Get-Content /tmp/ENI_ID

$autoscalinggroupname=$($($TAGS|ConvertFrom-Json).Tags|Where-Object {$_.key -eq "aws:autoscaling:groupName"}).Value
$privatesubnetslist=$($($TAGS|ConvertFrom-Json).Tags|Where-Object {$_.key -eq "PrivateSubnets"}).Value |ConvertFrom-Json
$logfrequency =$($($TAGS|ConvertFrom-Json).Tags|Where-Object {$_.key -eq "LogFrequency"}).Value


$route_tables= $(invoke-expression "aws ec2 describe-route-tables --filters `"Name=vpc-id,Values=$VPC_ID`" --region $REGION"|ConvertFrom-Json).RouteTables 
$autoscalinggroup=$(invoke-expression "aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $autoscalinggroupname --region $REGION"|ConvertFrom-Json).AutoScalingGroups
$ScaleConfig=  Get-ASG-ScalingConfig -TAGS $TAGS
$currentinstance=$($autoscalinggroup.Instances| where-object {$_.InstanceId -eq $INSTANCE_ID})

$privateroutetables=$route_tables| Where-Object {$_.Tags.Value -contains $STACKNAME}
$privatesubnetobjects=$($ALL_SUBNETS_LIST |convertfrom-json).Subnets |where-object { $privatesubnetslist  -contains $_.subnetid } |Sort-Object AvailabilityZone


#----------------------------------------------

#preliminary action
if (Test-first-run){
    Set-Association-SubnetsRouteTables -privateroutetables $privateroutetables -privatesubnetobjects $privatesubnetobjects -route_tables $route_tables -REGION $REGION
    Set-CW-Metrics-Config -REGION $REGION -INSTANCE_ID $INSTANCE_ID
}


#main action, setting routes and subnet associations
Mange-routes -autoscalinggroup $autoscalinggroup -privatesubnetobjects $privatesubnetobjects -privateroutetables $privateroutetables -logfrequency $logfrequency `
             -AZ_NAME $AZ_NAME -ENI_ID $ENI_ID -INSTANCE_ID $INSTANCE_ID -REGION $REGION 


#post action, scale up or down, if the later set scale in protection for other instances and fail over route.

Compare-CWMetrics-ASGScalingThresholds -REGION $REGION -INSTANCE_ID $INSTANCE_ID -AZ_NAME $AZ_NAME -ScaleConfig $ScaleConfig -autoscalinggroup $autoscalinggroup `
                                       -privatesubnetobjects $privatesubnetobjects -logfrequency $logfrequency

if( $currentinstance.ProtectedFromScaleIn -eq $true){
    
    Set-StateofEnvironment -counterpath "/tmp/ASGscaleinprotection"
    $counter=Get-Content -Path "/tmp/ASGscaleinprotection"

    if($counter -gt 5){
        #after 5 minutes remove scale in protection from the local instance
        Invoke-Expression "aws autoscaling  set-instance-protection --no-protected-from-scale-in --instance-ids  $($INSTANCE_Id) --auto-scaling-group-name $($autoscalinggroup.AutoScalingGroupARN.split("/")[1]) --region $REGION"
    }
}
else{
     if (test-path /tmp/ASGscaleinprotection) {
        Remove-Item -Path /tmp/ASGscaleinprotection
     }
}

#Todo1 test one AZ, multiple subnets.
#Todo2 add log rotation to /var/log/natm8.log