#notes: /16 = 65K ips 
# /23 172.20.0.1 - 172.20.1.254
#max vpc size is 14 https://docs.aws.amazon.com/vpc/latest/userguide/amazon-vpc-limits.html
import ipaddress
import os
import json
import urllib3
import json
import re
import logging
import boto3

SUCCESS = "SUCCESS"
FAILED = "FAILED"

http = urllib3.PoolManager()

print ('start of function')

def calculate_mask_vpc(subnetsize,subnetnumber):
	
	if subnetnumber == 2:
		vpcmaskdecrease=1
	elif  subnetnumber == 3 or  subnetnumber == 4:
		vpcmaskdecrease=2
	elif  subnetnumber >= 3 and  subnetnumber <= 8:
		vpcmaskdecrease=3
	else:
		vpcmaskdecrease=4
	
	result = subnetsize - vpcmaskdecrease
	return result

def calculate_mask_subnet(prefixlen_diff):
	
	if prefixlen_diff == 1:
		maxsubnet=2
	elif prefixlen_diff == 2:
		maxsubnet=4
	elif  prefixlen_diff == 3:
		maxsubnet=8
	elif  prefixlen_diff == 4:
		maxsubnet=16
	elif  prefixlen_diff == 5:
		maxsubnet=32
	elif  prefixlen_diff == 6:
		maxsubnet=64
	else:
		maxsubnet=128

	return maxsubnet

def determine_vpcmask(privatesubnetsize, privatesubnetnumber, publicsubnetsize, publicsubnetnumber, prs_reserve, pus_reserve, vpc_cidr):
	equalsize = False
	privatebigger = False

	if privatesubnetsize == publicsubnetsize:
		equalsize = True
		totalsubnetnumber=privatesubnetnumber+publicsubnetnumber+pus_reserve+prs_reserve
		initialvpcmasksize=calculate_mask_vpc(privatesubnetsize, totalsubnetnumber)
	elif privatesubnetsize <= publicsubnetsize:
		privatebigger = True
		initialvpcmasksize=calculate_mask_vpc(privatesubnetsize, privatesubnetnumber+prs_reserve)
		print('Initial VPC masksize: /' + str(initialvpcmasksize)+ ' calculated by using private regular and reserve subnets size and number.')
	else:
		initialvpcmasksize=calculate_mask_vpc(publicsubnetsize, publicsubnetnumber+pus_reserve)
		print('Initial VPC masksize: /' + str(initialvpcmasksize)+ ' calculated by using public regular and reserve subnets size and number.')
	
	if equalsize:
		print('The determined VPC masksize: /'+ str(initialvpcmasksize)+ ' fits the requested ' + str(privatesubnetnumber)+' private subnet '+str(publicsubnetnumber)+' public subnet '+str(pus_reserve)+' public subnet extension plus '+str(prs_reserve)+' private subnet extension. ')
	elif privatebigger:
		#The bigger subnet size will be the bases of subdividing. Eg private is /20, public is /22 then, 4 public fits in 1 private space. 
		# kudos https://stackoverflow.com/questions/63019003/how-to-get-all-possible-subnet-id-of-a-network-in-python
		fullAddressCandidate = ipaddress.ip_network(vpc_cidr + '/' + str(initialvpcmasksize))
		addressCandidateList = list(fullAddressCandidate.subnets(prefixlen_diff=(publicsubnetsize-privatesubnetsize)))
		
		if ((privatesubnetnumber+prs_reserve) >= len(addressCandidateList)): 
			initialvpcmasksize=initialvpcmasksize-1
			EntireAddressSpace = ipaddress.ip_network(vpc_cidr + '/' + str(initialvpcmasksize))
			AllAddresscount = len(list(EntireAddressSpace.subnets(prefixlen_diff=(privatesubnetsize-initialvpcmasksize))))
			print('Increasing VPC masksize: /'+ str(initialvpcmasksize) +' to make room for more subnets')
		else:
			print('The required number of Private subnets fit into initial VPC mask size')
					
		maxsubnetspervlsm=calculate_mask_subnet(publicsubnetsize-privatesubnetsize)
		availablesubnets=AllAddresscount - (privatesubnetnumber+prs_reserve)
		totalvlsmsubnets=availablesubnets*maxsubnetspervlsm

		if(totalvlsmsubnets < (publicsubnetnumber+pus_reserve)):
			initialvpcmasksize=initialvpcmasksize-1
			print('Further Increasing VPC masksize to '+ str(initialvpcmasksize) +' to make room for more public subnets')
		else:
			print('The required number of subnets fit into the existing  /' + str(initialvpcmasksize) + ' VPC mask size')
	else:
		#The reverse Eg public is /20, private is /22 then, 4 private fits in 1 public space. 
		fullAddressCandidate = ipaddress.ip_network(vpc_cidr + '/' + str(initialvpcmasksize))
		addressCandidateList = list(fullAddressCandidate.subnets(prefixlen_diff=(privatesubnetsize-publicsubnetsize)))

		if ((publicsubnetnumber+pus_reserve) >= len(addressCandidateList)): 
			initialvpcmasksize=initialvpcmasksize-1
			EntireAddressSpace = ipaddress.ip_network(vpc_cidr + '/' + str(initialvpcmasksize))
			AllAddresscount = len(list(EntireAddressSpace.subnets(prefixlen_diff=(publicsubnetsize-initialvpcmasksize))))
			print('Further Increasing VPC masksize: /'+ str(initialvpcmasksize) +' to make room for more subnets')
		else:
			print('The required number of subnets fit into the existing  /' + str(initialvpcmasksize) + ' VPC mask size')
				
		maxsubnetspervlsm=calculate_mask_subnet(privatesubnetsize-publicsubnetsize)
		availablesubnets=AllAddresscount - (privatesubnetnumber+prs_reserve)
		totalvlsmsubnets=availablesubnets*maxsubnetspervlsm
		
		if(totalvlsmsubnets < (publicsubnetnumber+pus_reserve)):
			initialvpcmasksize=initialvpcmasksize-1
			print('Further Increasing VPC masksize: /'+ str(initialvpcmasksize) +' to make room for more public subnets')
		else:
			print('The required number of subnets fit into the existing /' + str(initialvpcmasksize) + ' VPC mask size')

	return  initialvpcmasksize    

def inform_user(vpc_cidr, vpcmasksize, privatesubnetsize, publicsubnetsize):

	if privatesubnetsize == publicsubnetsize:
		subnetlist=ipaddress.ip_network(str(vpc_cidr) + '/' + str(vpcmasksize))
		addressCandidateList = list(subnetlist.subnets(prefixlen_diff=(privatesubnetsize-vpcmasksize)))
		addresslist=str(addressCandidateList).replace('IPv4Network(', '').replace(')', '')
		print('\nThe address space of all VPC subnets:\n' + addresslist)

	elif privatesubnetsize <= publicsubnetsize:
		subnetlist=ipaddress.ip_network(str(vpc_cidr) + '/' + str(vpcmasksize))
		addressCandidateList = list(subnetlist.subnets(prefixlen_diff=(privatesubnetsize-vpcmasksize)))
		addresslist=str(addressCandidateList).replace('IPv4Network(', '').replace(')', '')
		print('\nThe address space of the *VPC*, using the larger (private) subnet size:\n ' + addresslist)

	else:
		subnetlist=ipaddress.ip_network(str(vpc_cidr) + '/' + str(vpcmasksize))
		addressCandidateList = list(subnetlist.subnets(prefixlen_diff=(publicsubnetsize-vpcmasksize)))
		addresslist=str(addressCandidateList).replace('IPv4Network(', '').replace(')', '')
		print('\nThe address space of the *VPC*, using the larger (public) subnet size:\n' + addresslist)

def helper_larger_addresslist_array(subnetsize, vpcmasksize, vpc_cidr, maxsubnetspervlsm):    
	subnetlist=ipaddress.ip_network(str(vpc_cidr) + '/' + str(vpcmasksize))
	addressCandidateList = list(subnetlist.subnets(prefixlen_diff=(subnetsize-vpcmasksize)))
	addresslist=str(addressCandidateList).replace('IPv4Network(', '').replace(')', '').replace('[', '').replace(']', '').replace("'", '')
	addresslistarray=addresslist.split(', ')
	return addresslistarray

def helper_smaller_addresslist_array(subnetrangeall, subnet1size, subnet2size):
	EntireAddressSpace = ipaddress.ip_network(subnetrangeall + '/' + str(subnet1size))
	Allpublicsubnets = list(EntireAddressSpace.subnets(prefixlen_diff=(subnet2size-subnet1size)))
	addresslist=str(Allpublicsubnets).replace('IPv4Network(', '').replace(')', '').replace('[', '').replace(']', '').replace("'", '')
	addresslistarray=addresslist.split(', ')
	return addresslistarray

def allocate_subnets(vpc_cidr, vpcmasksize, privatesubnetsize, publicsubnetsize, privatesubnetnumber, privatereserve, publicsubnetnumber, publicreserve, public_location):
   
	subnetsused=0
	#1) determine which is the larger subnet public or priate or equal size 
	#2) how many of the larger subnets ranges are needed for the smaller subnet ranges,
	#   given the smaller subnet range size and required number
	#3) based on the public location at start or end select the required number of subnets
	if privatesubnetsize < publicsubnetsize:
		
		maxsubnetspervlsm=calculate_mask_subnet(privatesubnetsize -vpcmasksize)    
		addresslistarrayprivate = helper_larger_addresslist_array(privatesubnetsize, vpcmasksize, vpc_cidr, maxsubnetspervlsm)

		if maxsubnetspervlsm >=(privatesubnetnumber+privatereserve):    
			subnetsused=1
			start=1
			end=len(addresslistarrayprivate)-(subnetsused)
		else:
			subnetsused=2
			start=2
			end=len(addresslistarrayprivate)-(subnetsused)
			privatesubnetsize=privatesubnetsize-1

		if public_location =='start': 
			publicsubnetrangeall=addresslistarrayprivate[:subnetsused][0].split('/')[0]
		else:
			publicsubnetrangeall=addresslistarrayprivate[end:(end+subnetsused)][0].split('/')[0]

		addresslistarraypublic = helper_smaller_addresslist_array(publicsubnetrangeall, privatesubnetsize, publicsubnetsize)

		if public_location =='start': 
				
			privatesubnetrange=addresslistarrayprivate[start:privatesubnetnumber+subnetsused]
			publicsubnetrangeall=addresslistarraypublic[:publicsubnetnumber]

			print('\nThe generated private range(s): '+str(privatesubnetrange)) 
			print('\nThe generated  public range(s): '+str(publicsubnetrangeall)) 
			print('\n') 
		else:
			#in this case the public subnets are at the end of the VPC range
			privatesubnetrange=addresslistarrayprivate[:privatesubnetnumber]
			publicsubnetrangeall=addresslistarraypublic[:publicsubnetnumber]

			print('\nThe generated private range(s): '+str(privatesubnetrange)) 
			print('\nThe generated  public range(s): '+str(publicsubnetrangeall)) 
			print('\n') 

		result = 'public:'+str(publicsubnetrangeall)+'private:'+str(privatesubnetrange)+'vpcmasksize:'+str(vpcmasksize)
		result=result.replace('[', '').replace(']', ';').replace(' ', '').replace("'", '')
	elif privatesubnetsize > publicsubnetsize:
		maxsubnetspervlsm=calculate_mask_subnet(publicsubnetsize -vpcmasksize)    
		addresslistarrayvpc = helper_larger_addresslist_array(publicsubnetsize, vpcmasksize, vpc_cidr, maxsubnetspervlsm)

		if maxsubnetspervlsm >=(publicsubnetnumber+publicreserve):
			subnetsused=1
			start=1
			end=len(addresslistarrayvpc)-(subnetsused)
		else:
			subnetsused=2
			end=len(addresslistarrayvpc)-(subnetsused)
			privatesubnetsize=privatesubnetsize-1

		if public_location =='start': 
			#in this case the private subnets are at the end of the VPC range
			publicsubnetrange=addresslistarrayvpc[0:publicsubnetnumber+subnetsused]
			privatesubnetrange=addresslistarrayvpc[end:(end+subnetsused)][0].split('/')[0]
			addresslistarrayprivate = helper_smaller_addresslist_array(privatesubnetrange, publicsubnetsize, privatesubnetsize)
			privatesubnetrangeall=addresslistarrayprivate[:privatesubnetnumber]
			publicsubnetrangeall=publicsubnetrange

			print('\nThe generated private range(s): '+str(privatesubnetrangeall)) 
			print('\nThe generated public range(s): '+str(publicsubnetrangeall)) 
			print('\n') 
		else:
			#in this case the private subnets are at the start of the VPC range
			publicsubnetrange=addresslistarrayvpc[(publicsubnetnumber+publicreserve):][0].split('/')[0]
			privatesubnetrange=addresslistarrayvpc[:privatesubnetnumber][0].split('/')[0]
			addresslistarrayprivate = helper_smaller_addresslist_array(privatesubnetrange, publicsubnetsize, privatesubnetsize)
			privatesubnetrangeall=addresslistarrayprivate[:publicsubnetnumber]
			publicsubnetrangeall=addresslistarrayvpc[subnetsused:(publicsubnetnumber+publicreserve):]

			print('\nThe generated private range(s): '+str(privatesubnetrangeall)) 
			print('\nThe generated public range(s): '+str(publicsubnetrangeall))
			print('\n') 

		result = 'public:'+str(publicsubnetrangeall)+'private:'+str(privatesubnetrange)+'vpcmasksize:'+str(vpcmasksize)
		result=result.replace('[', '').replace(']', ';').replace(' ', '').replace("'", '')

	elif privatesubnetsize == publicsubnetsize:
		maxsubnetspervlsm=calculate_mask_subnet(privatesubnetsize -vpcmasksize)    
		addresslistarrayvpc = helper_larger_addresslist_array(privatesubnetsize, vpcmasksize, vpc_cidr, maxsubnetspervlsm)

		if public_location =='start': 
			publicsubnetrangeall=addresslistarrayvpc[:publicsubnetnumber+pus_reserve]
			privatesubnetrange=addresslistarrayvpc[(privatesubnetnumber+prs_reserve):((privatesubnetnumber+prs_reserve)+publicsubnetnumber+pus_reserve)]

			print('\nThe generated private range(s): '+str(privatesubnetrange)) 
			print('\nThe generated  public range(s): '+str(publicsubnetrangeall)) 
			print('\n') 
		else:
			#in this case the public subnets are at the end of the VPC range
			subnetsused=publicsubnetnumber+ pus_reserve
			end=len(addresslistarrayvpc)-(subnetsused)
			privatesubnetrange=addresslistarrayvpc[:publicsubnetnumber+pus_reserve] 
			publicsubnetrangeall=addresslistarrayvpc[end:(end+subnetsused)]

			print('\nThe generated private range(s): '+str(privatesubnetrange)) 
			print('\nThe generated  public range(s): '+str(publicsubnetrangeall)) 
			print('\n') 

		result = 'public:'+str(publicsubnetrangeall)+'private:'+str(privatesubnetrange)+'vpcmasksize:'+str(vpcmasksize)
		result=result.replace('[', '').replace(']', ';').replace(' ', '').replace("'", '')

	return result

def iprangegenerator(privatesubnetsize, privatesubnetnumber, publicsubnetsize, publicsubnetnumber, prs_reserve, pus_reserve, vpc_cidr, vpcmasksize, public_location):
	
	print ('start of iprangegenerator function')
	
	#show larger subnet's all address ranges. 
	inform_user(vpc_cidr, vpcmasksize, privatesubnetsize,publicsubnetsize)

	#main application logic
	result =allocate_subnets(vpc_cidr, vpcmasksize, privatesubnetsize, publicsubnetsize, privatesubnetnumber,prs_reserve, publicsubnetnumber,pus_reserve, public_location)
	
	return result

def filter_objects(array, condition1):
    return [obj for obj in array if condition1(obj) ] #and condition2(obj)

def get_networkinfo(cfnclient, Stackname):

	cfnresponse = cfnclient.describe_stack_resources(
			StackName=Stackname
	)

	allsubnets = filter_objects(
		cfnresponse['StackResources'],
		lambda x: x['ResourceType'] == 'AWS::EC2::Subnet'
	)

	public_subnets = filter_objects(
		allsubnets,
		lambda x: x['LogicalResourceId'].startswith('Public')
	)

	private_subnets = filter_objects(
		allsubnets,
		lambda x: x['LogicalResourceId'].startswith('Private')
	)

	# vpc_resource = filter_objects(
	# 	cfnresponse['StackResources'],
	# 	lambda x: x['ResourceType'] == 'AWS::EC2::VPC'
	# )

	result = {
		'public': list(map(lambda d: d['PhysicalResourceId'], public_subnets)),
		'private': list(map(lambda d: d['PhysicalResourceId'], private_subnets))
		#,'vpcid': vpc_resource[0]['PhysicalResourceId']
	}

	return result

def helper_cfn_AutoM8_service_params(vpc_id, vpc_range, networkparams, S3Bucket ):
	stackparameters =  [
			{
				'ParameterKey': 'VpcId',
				'ParameterValue': vpc_id
			},
			{
				'ParameterKey': 'VpcCidr',
				'ParameterValue': vpc_range
			},
			{
				'ParameterKey': 'PublicSubnets',
				'ParameterValue': str(networkparams['public']).replace('[', '').replace(']', '').replace("'", "")
			},
			{
				'ParameterKey': 'PrivateSubnets',
				'ParameterValue': str(networkparams['private']).replace('[', '').replace(']', '').replace("'", "")
			},
			{
				'ParameterKey': 'NATConfigBucket',
				'ParameterValue': S3Bucket
			},
			{
				'ParameterKey': 'NATRoutingScript',
				'ParameterValue': 'ConfigureRoutes.ps1'
			},
			{
				'ParameterKey': 'NatServerKey',
				'ParameterValue': ''
			}
			
    	]
	return stackparameters 

def helper_cfn_AutoM8_VPC_parameters(vpc_cidr, generated_vpc_config, publicsubnetnumber, privatesubnetnumber, instance_type_x64, instance_type_arm, instance_desired_number, instance_minimum_number, validate_configuration, function_arn, sources_version):
	stackparameters =  [

			{
				'ParameterKey': 'VpcCIDR',
				'ParameterValue': vpc_cidr
			},
			{
				'ParameterKey': 'PublicSubnetnumber',
				'ParameterValue': str(publicsubnetnumber)
			},
			{
				'ParameterKey': 'PrivateSubnetnumber',
				'ParameterValue': str(privatesubnetnumber)
			},
			{
				'ParameterKey': 'GeneratedVPCConfig',
				'ParameterValue': generated_vpc_config
			},
			{
				'ParameterKey': 'InstanceTypeX64',
				'ParameterValue': instance_type_x64
			},
			{
				'ParameterKey': 'InstanceTypeARM',
				'ParameterValue': instance_type_arm
			},
			{
				'ParameterKey': 'InstanceDesiredNumber',
				'ParameterValue': str(instance_desired_number)
			},
			{
				'ParameterKey': 'InstanceMinimumNumber',
				'ParameterValue': str(instance_minimum_number)
			},
			{
				'ParameterKey': 'ValidateConfiguration',
				'ParameterValue': validate_configuration
			},
			{
				'ParameterKey': 'FunctionARN',
				'ParameterValue': function_arn
			},
			{
				'ParameterKey': 'SourcesVersion',
				'ParameterValue': sources_version
			}
			
    	]
	return stackparameters 

def helper_cfn_NATM8_parameters(vpc_id, vpc_cidr, public_subnets_list, private_subnets_list, instance_desired_number, instance_minimum_number, instance_type_x64, instance_type_arm, cw_logs_metrics_config, ondemand_purchase_percentage):

	stackparameters =  [

			{
				'ParameterKey': 'VpcId',
				'ParameterValue': vpc_id
			},
			{
				'ParameterKey': 'VpcCidr',
				'ParameterValue': vpc_cidr
			},
			{
				'ParameterKey': 'PublicSubnets',
				'ParameterValue': str(public_subnets_list).replace('[', '').replace(']', '').replace("'", "")
			},
			{
				'ParameterKey': 'PrivateSubnets',
				'ParameterValue': str(private_subnets_list).replace('[', '').replace(']', '').replace("'", "")
			},
			{
				'ParameterKey': 'InstanceDesiredNumber',
				'ParameterValue': str(instance_desired_number)
			},
			{
				'ParameterKey': 'InstanceMinimumNumber',
				'ParameterValue': str(instance_minimum_number)
			},
			{
				'ParameterKey': 'InstanceTypeX64',
				'ParameterValue': instance_type_x64
			},
			{
				'ParameterKey': 'InstanceTypeARM',
				'ParameterValue': instance_type_arm
			},
			{
				'ParameterKey': 'CWLogsandMetricsConfig',
				'ParameterValue': cw_logs_metrics_config
			},
			{
				'ParameterKey': 'OnDemandPurchasePercentage',
				'ParameterValue': str(ondemand_purchase_percentage)
			},
			{
				'ParameterKey': 'NatServerKey',
				'ParameterValue': ''
			}
			
    	]
	
	return stackparameters 

def cfnsend(event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False, reason=None):
    responseUrl = event['ResponseURL']

    responseBody = {
        'Status' : responseStatus,
        'Reason' : reason or "See the details in CloudWatch Log Stream: {}".format(context.log_stream_name),
        'PhysicalResourceId' : physicalResourceId or context.log_stream_name,
        'StackId' : event['StackId'],
        'RequestId' : event['RequestId'],
        'LogicalResourceId' : event['LogicalResourceId'],
        'NoEcho' : noEcho,
        'Data' : responseData
    }

    json_responseBody = json.dumps(responseBody)

    print("Response body:")
    print(json_responseBody)

    headers = {
        'content-type' : '',
        'content-length' : str(len(json_responseBody))
    }

    try:
        response = http.request('PUT', responseUrl, headers=headers, body=json_responseBody)
        print("Status code:", response.status)


    except Exception as e:

        print("send(..) failed executing http.request(..):", mask_credentials_and_signature(e))

def mask_credentials_and_signature(message):
    message = re.sub(r'X-Amz-Credential=[^&\s]+', 'X-Amz-Credential=*****', message, flags=re.IGNORECASE)
    return re.sub(r'X-Amz-Signature=[^&\s]+', 'X-Amz-Signature=*****', message, flags=re.IGNORECASE)

def copysources(s3client, S3Bucket):
	s3client.meta.client.upload_file('./NATM8/NATM8.json', S3Bucket, 'NATM8.json')
	s3client.meta.client.upload_file('./NATM8/NAT_AutoM8.json', S3Bucket, 'NAT_AutoM8.json')
	s3client.meta.client.upload_file('./NATM8/ConfigureRoutes.ps1', S3Bucket, 'ConfigureRoutes.ps1')
	print("\n\ns3 copy done")

def main(event, context):
	
	LOGGER = logging.getLogger()
	LOGGER.setLevel(logging.INFO)
	LOGGER.info('REQUEST EVENT RECEIVED:\n %s', event)
	LOGGER.info('REQUEST CONTEXT RECEIVED:\n %s', context)

	cfnclient = boto3.client('cloudformation')
	s3client = boto3.resource('s3')
	resourcetype = event['ResourceType']
	requesttype = event['RequestType']

	#setting up environment variables
	if ((event['ResourceType']) == "Custom::GenerateIPranges" ):
		#NAT Auto M8 create ip ranges for new VPC
		prs_reserve = int(event['ResourceProperties']['PrivateSubnetReserve'])
		privatesubnetnumber = int(event['ResourceProperties']['PrivateSubnetnumber'])
		privatesubnetsize = int(event['ResourceProperties']['PrivateSubnetsize'])
		pus_reserve = int(event['ResourceProperties']['PublicSubnetReserve'])
		publicsubnetnumber = int(event['ResourceProperties']['PublicSubnetnumber'])
		publicsubnetsize = int(event['ResourceProperties']['PublicSubnetsize'])
		vpc_cidr = event['ResourceProperties']['VpcCIDR']
		public_location = event['ResourceProperties']['PublicSubnetLocation']
		S3Bucket =os.environ.get('S3Bucket')
		
	elif((event['ResourceType']) == "Custom::DeployVPC"):
		#NAT Auto M8 create new VPC or update its settings
		vpc_cidr=event['ResourceProperties']['VpcCIDR']
		publicsubnetnumber = int(event['ResourceProperties']['PublicSubnetnumber'])
		privatesubnetnumber = int(event['ResourceProperties']['PrivateSubnetnumber'])
		generated_vpc_config=event['ResourceProperties']['GeneratedVPCConfig']
		instance_type_x64=event['ResourceProperties']['InstanceTypeX64']
		instance_type_arm=event['ResourceProperties']['InstanceTypeARM']
		instance_desired_number=event['ResourceProperties']['InstanceDesiredNumber']
		instance_minimum_number=event['ResourceProperties']['InstanceMinimumNumber']
		validate_configuration=event['ResourceProperties']['ValidateConfiguration']
		sources_version=event['ResourceProperties']['SourcesVersion']
		function_arn=event['ResourceProperties']['FunctionARN']
		S3Bucket =os.environ.get('S3Bucket')
		region = os.environ.get('Region')
	
	elif((event['ResourceType']) == "Custom::DeployNATAUTOM8"):
		#NATM8 deployed as part of NAT Auto M8 (to new vpc)
		S3Bucket =os.environ.get('S3Bucket')
		region = os.environ.get('Region')
		Stackname=event['ResourceProperties']['StackName']
		vpc_id=event['ResourceProperties']['VPCID']
		vpc_range=event['ResourceProperties']['vpcrange']

	elif((event['ResourceType']) == "Custom::DeployNATM8"):
		#NATM8 deployed solo (to existing vpc)
		S3Bucket =os.environ.get('S3Bucket')
		region = os.environ.get('Region')
		vpc_id=event['ResourceProperties']['VPCID']
		vpc_cidr=event['ResourceProperties']['VpcCIDR']
		public_subnets_list=event['ResourceProperties']['PublicSubnets']
		private_subnets_list=event['ResourceProperties']['PrivateSubnets']
		instance_desired_number=event['ResourceProperties']['InstanceDesiredNumber']
		instance_minimum_number=event['ResourceProperties']['InstanceMinimumNumber']
		instance_type_x64=event['ResourceProperties']['InstanceTypeX64']
		instance_type_arm=event['ResourceProperties']['InstanceTypeARM']
		cw_logs_metrics_config=event['ResourceProperties']['CWLogsandMetricsConfig']
		ondemand_purchase_percentage=event['ResourceProperties']['OnDemandPurchasePercentage']


	else:
		#local test and troubleshoothing settings #TBD cahnges
		publicsubnetsize = 22
		privatesubnetsize = 20
		publicsubnetnumber = 3
		privatesubnetnumber = 3
		pus_reserve = 1
		prs_reserve = 1
		vpc_cidr ='172.20.0.0'
		vpc_id='vpc-064030f7ce8312247'
		vpc_range='172.29.0.0/17'
		public_location='end' #start #end
		S3Bucket = 'logverzvpc-testing-bootstrapbucket-jsrwbspkbbyv'
		Stackname = 'LogverzVPC-testing'
		resourcetype = 'Custom::DeployNATAUTOM8' #'Custom::GenerateIPranges'
		requesttype = 'Update' #'Create'
		region='ap-southeast-2'
	#end of setting up environemnt variables

	if (resourcetype == 'Custom::GenerateIPranges'):
		#(requesttype == 'Create' or requesttype == 'Update' ) and 
		#incase its a new VPC creation we call the ip generator to retrieve the ranges. 
		#determine required VPC size (mask number)
		vpcmasksize = determine_vpcmask(privatesubnetsize, privatesubnetnumber, publicsubnetsize, publicsubnetnumber, prs_reserve, pus_reserve, vpc_cidr)
		result = iprangegenerator(privatesubnetsize, privatesubnetnumber, publicsubnetsize, publicsubnetnumber, prs_reserve, pus_reserve, vpc_cidr, vpcmasksize, public_location)
		print(result)

		cfnsend(event, context, "SUCCESS", {"Message": result})

	elif (resourcetype == 'Custom::DeployVPC' and requesttype == 'Create'):
		copysources(s3client, S3Bucket)
		stackparameters = helper_cfn_AutoM8_VPC_parameters(vpc_cidr, generated_vpc_config, publicsubnetnumber, privatesubnetnumber, instance_type_x64, instance_type_arm, instance_desired_number, instance_minimum_number, validate_configuration, function_arn, sources_version)
		print('Stack Parameters:\n\n', stackparameters)
		cfnclient.create_stack(
			StackName='NATAutoM8-VPCSettings',
			TemplateURL='https://' + S3Bucket +'.s3.' + region +'.amazonaws.com/NAT_AutoM8.json',
			Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'],
			Parameters=stackparameters
			#,OnFailure='DO_NOTHING'
		)
		print('CFN deployment started')
		cfnsend(event, context, "SUCCESS", {"Message": "VPCDeploymentStarted"})
	
	elif (resourcetype == 'Custom::DeployVPC' and requesttype == 'Update'):
		copysources(s3client, S3Bucket)
		stackparameters = helper_cfn_AutoM8_VPC_parameters(vpc_cidr, generated_vpc_config, publicsubnetnumber, privatesubnetnumber, instance_type_x64, instance_type_arm, instance_desired_number, instance_minimum_number, validate_configuration, function_arn, sources_version)
		print('Stack Parameters:\n\n', stackparameters)
		cfnclient.update_stack(
			StackName='NATAutoM8-VPCSettings',
			TemplateURL='https://' + S3Bucket +'.s3.' + region +'.amazonaws.com/NAT_AutoM8.json',
			Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'],
			Parameters=stackparameters
			#,OnFailure='DO_NOTHING'
		)
		print('CFN deployment started')
		cfnsend(event, context, "SUCCESS", {"Message": "VPCDeploymentStarted"})

	elif (resourcetype == 'Custom::DeployNATAUTOM8' and requesttype == 'Create'):
		#in case its after subnet and vpc have been deployed. We start Nat M8 installation.
		networkparams= get_networkinfo(cfnclient, Stackname)
		stackparameters = helper_cfn_AutoM8_service_params(vpc_id, vpc_range, networkparams, S3Bucket )
		print('Stack Parameters:\n\n', stackparameters)
		cfnclient.create_stack(
			StackName='NATAutoM8-Service',
			TemplateURL='https://' + S3Bucket +'.s3.' + region +'.amazonaws.com/NATM8.json',
			Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'],
			Parameters=stackparameters
			#,OnFailure='DO_NOTHING'
		)
		print('CFN deployment started')
		cfnsend(event, context, "SUCCESS", {"Message": "NATM8DeploymentStarted"})

	elif (resourcetype == 'Custom::DeployNATAUTOM8' and requesttype == 'Update'):
		#in case its after subnet and vpc have been deployed. We start Nat M8 installation.
		networkparams= get_networkinfo(cfnclient, Stackname)
		stackparameters = helper_cfn_AutoM8_service_params(vpc_id, vpc_range, networkparams, S3Bucket )
		print('Stack Parameters:\n\n', stackparameters)

		cfnclient.update_stack(
		#cfnclient.create_stack(
			StackName='NATAutoM8-Service',
			TemplateURL='https://' + S3Bucket +'.s3.' + region +'.amazonaws.com/NATM8.json',
			Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'],
			Parameters=stackparameters
			#,OnFailure='DO_NOTHING'
		)
		print('CFN update started')
		cfnsend(event, context, "SUCCESS", {"Message": "NATM8UpdateStarted"})

	elif (resourcetype == 'Custom::DeployNATM8' and requesttype == 'Create'):
		copysources(s3client, S3Bucket)
		stackparameters = helper_cfn_NATM8_parameters(vpc_id, vpc_cidr, public_subnets_list, private_subnets_list, instance_desired_number, instance_minimum_number, instance_type_x64, instance_type_arm, cw_logs_metrics_config, ondemand_purchase_percentage)
		print('Stack Parameters:\n\n', stackparameters)
		cfnclient.create_stack(
			StackName='NATM8-Service',
			TemplateURL='https://' + S3Bucket +'.s3.' + region +'.amazonaws.com/NATM8.json',
			Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'],
			Parameters=stackparameters
			#,OnFailure='DO_NOTHING'
		)
		print('CFN deployment started')
		cfnsend(event, context, "SUCCESS", {"Message": "NATM8DeploymentStarted"})

	elif (resourcetype == 'Custom::DeployNATM8' and requesttype == 'Update'):
		copysources(s3client, S3Bucket)
		stackparameters = helper_cfn_NATM8_parameters(vpc_id, vpc_cidr, public_subnets_list, private_subnets_list, instance_desired_number, instance_minimum_number, instance_type_x64, instance_type_arm, cw_logs_metrics_config, ondemand_purchase_percentage)
		print('Stack Parameters:\n\n', stackparameters)

		cfnclient.update_stack(
		#cfnclient.create_stack(
			StackName='NATM8-Service',
			TemplateURL='https://' + S3Bucket +'.s3.' + region +'.amazonaws.com/NATM8.json',
			Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'],
			Parameters=stackparameters
			#,OnFailure='DO_NOTHING'
		)
		print('CFN update started')
		cfnsend(event, context, "SUCCESS", {"Message": "NATM8UpdateStarted"})
	
	else:
		cfnsend(event, context, "SUCCESS", {"Message": "NoActionTaken"})

# Local Testing config
# event ={"ResourceProperties":{"VpcCIDR":""}}
# context = ""
# main(event, context)

print ('end of function')