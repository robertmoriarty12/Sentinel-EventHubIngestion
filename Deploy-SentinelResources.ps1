<#
.SYNOPSIS
    Deploys Data Collection Endpoint, Data Collection Rule, and Custom Table for Event Hub to Sentinel ingestion.

.DESCRIPTION
    This script creates the necessary Azure resources to ingest Event Hub data into Microsoft Sentinel:
    - Data Collection Endpoint (DCE)
    - Custom Log Analytics Table
    - Data Collection Rule (DCR)

.PARAMETER ResourceGroupName
    The name of the resource group where resources will be created.

.PARAMETER WorkspaceName
    The name of the Log Analytics/Sentinel workspace.

.PARAMETER Location
    Azure region for the resources (e.g., eastus, westus2).

.PARAMETER TableName
    Name of the custom table (without _CL suffix). Default: EventHubData

.EXAMPLE
    .\Deploy-SentinelResources.ps1 -ResourceGroupName "rg-sentinel" -WorkspaceName "sentinel-workspace" -Location "eastus"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$true)]
    [string]$WorkspaceName,

    [Parameter(Mandatory=$true)]
    [string]$Location,

    [Parameter(Mandatory=$false)]
    [string]$TableName = "EventHubData"
)

$ErrorActionPreference = "Stop"

Write-Host "========================================================================================================" -ForegroundColor Cyan
Write-Host "Event Hub to Sentinel - Resource Deployment" -ForegroundColor Cyan
Write-Host "========================================================================================================" -ForegroundColor Cyan
Write-Host ""

# Variables
$dceName = "eventhub-dce-$(Get-Random -Maximum 9999)"
$dcrName = "EventHubDataDCR"
$customTableName = "${TableName}_CL"
$streamName = "Custom-${customTableName}"

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Resource Group: $ResourceGroupName" -ForegroundColor White
Write-Host "  Workspace: $WorkspaceName" -ForegroundColor White
Write-Host "  Location: $Location" -ForegroundColor White
Write-Host "  DCE Name: $dceName" -ForegroundColor White
Write-Host "  DCR Name: $dcrName" -ForegroundColor White
Write-Host "  Table Name: $customTableName" -ForegroundColor White
Write-Host "  Stream Name: $streamName" -ForegroundColor White
Write-Host ""

# Verify Azure CLI is installed
Write-Host "[1/5] Verifying Azure CLI..." -ForegroundColor Yellow
try {
    $azVersion = az version --query '\"azure-cli\"' -o tsv 2>$null
    Write-Host "  ✓ Azure CLI version $azVersion found" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Azure CLI not found. Please install from: https://docs.microsoft.com/cli/azure/install-azure-cli" -ForegroundColor Red
    exit 1
}

# Check if logged in
Write-Host "  Checking Azure login status..." -ForegroundColor White
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "  ✗ Not logged in to Azure. Running 'az login'..." -ForegroundColor Yellow
    az login
    $account = az account show | ConvertFrom-Json
}
Write-Host "  ✓ Logged in as: $($account.user.name)" -ForegroundColor Green
Write-Host "  ✓ Subscription: $($account.name)" -ForegroundColor Green
Write-Host ""

# Get workspace resource ID
Write-Host "[2/5] Getting Log Analytics Workspace information..." -ForegroundColor Yellow
$workspaceId = az monitor log-analytics workspace show `
    --resource-group $ResourceGroupName `
    --workspace-name $WorkspaceName `
    --query id -o tsv

if (-not $workspaceId) {
    Write-Host "  ✗ Workspace '$WorkspaceName' not found in resource group '$ResourceGroupName'" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ Workspace found: $workspaceId" -ForegroundColor Green
Write-Host ""

# Create Data Collection Endpoint
Write-Host "[3/5] Creating Data Collection Endpoint..." -ForegroundColor Yellow
$dceJson = az monitor data-collection endpoint create `
    --name $dceName `
    --resource-group $ResourceGroupName `
    --location $Location `
    --public-network-access Enabled `
    2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Failed to create Data Collection Endpoint" -ForegroundColor Red
    Write-Host "  Error: $dceJson" -ForegroundColor Red
    exit 1
}

$dce = $dceJson | ConvertFrom-Json
$dceEndpoint = $dce.logsIngestion.endpoint
$dceId = $dce.id

Write-Host "  ✓ DCE created successfully" -ForegroundColor Green
Write-Host "    Endpoint: $dceEndpoint" -ForegroundColor White
Write-Host ""

# Create Custom Table
Write-Host "[4/5] Creating Custom Log Table..." -ForegroundColor Yellow

# Define table schema based on sample Event Hub data
$tableSchema = @{
    properties = @{
        schema = @{
            name = $customTableName
            columns = @(
                @{ name = "TimeGenerated"; type = "datetime"; description = "Timestamp when data was generated" }
                @{ name = "EventHubPartitionId"; type = "string"; description = "Event Hub partition ID" }
                @{ name = "EventHubSequenceNumber"; type = "long"; description = "Event Hub sequence number" }
                @{ name = "EventHubOffset"; type = "string"; description = "Event Hub offset" }
                @{ name = "EventHubEnqueuedTime"; type = "datetime"; description = "When event was enqueued in Event Hub" }
                @{ name = "RawData"; type = "string"; description = "Original JSON data from Event Hub" }
                @{ name = "id"; type = "int"; description = "Event ID" }
                @{ name = "time_generated"; type = "string"; description = "Time generated from source data" }
                @{ name = "sensor"; type = "string"; description = "Sensor type" }
                @{ name = "value"; type = "real"; description = "Sensor value" }
                @{ name = "location"; type = "string"; description = "Sensor location" }
            )
        }
    }
}

$tableSchemaJson = $tableSchema | ConvertTo-Json -Depth 10 -Compress

# Create table using REST API (Azure CLI doesn't support custom table creation directly)
$token = az account get-access-token --query accessToken -o tsv
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

$tableUri = "https://management.azure.com$workspaceId/tables/${customTableName}?api-version=2022-10-01"

try {
    $response = Invoke-RestMethod -Uri $tableUri -Method Put -Headers $headers -Body $tableSchemaJson
    Write-Host "  ✓ Custom table '$customTableName' created successfully" -ForegroundColor Green
} catch {
    if ($_.Exception.Response.StatusCode -eq 409) {
        Write-Host "  ⚠ Table '$customTableName' already exists, continuing..." -ForegroundColor Yellow
    } else {
        Write-Host "  ✗ Failed to create table: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}
Write-Host ""

# Create Data Collection Rule
Write-Host "[5/5] Creating Data Collection Rule..." -ForegroundColor Yellow

$dcrDefinition = @{
    location = $Location
    properties = @{
        dataCollectionEndpointId = $dceId
        streamDeclarations = @{
            $streamName = @{
                columns = @(
                    @{ name = "TimeGenerated"; type = "datetime" }
                    @{ name = "EventHubPartitionId"; type = "string" }
                    @{ name = "EventHubSequenceNumber"; type = "long" }
                    @{ name = "EventHubOffset"; type = "string" }
                    @{ name = "EventHubEnqueuedTime"; type = "datetime" }
                    @{ name = "RawData"; type = "string" }
                    @{ name = "id"; type = "int" }
                    @{ name = "time_generated"; type = "string" }
                    @{ name = "sensor"; type = "string" }
                    @{ name = "value"; type = "real" }
                    @{ name = "location"; type = "string" }
                )
            }
        }
        destinations = @{
            logAnalytics = @(
                @{
                    workspaceResourceId = $workspaceId
                    name = "clv2ws1"
                }
            )
        }
        dataFlows = @(
            @{
                streams = @($streamName)
                destinations = @("clv2ws1")
                transformKql = "source"
                outputStream = $streamName
            }
        )
    }
}

$dcrJson = $dcrDefinition | ConvertTo-Json -Depth 10 -Compress
$dcrUri = "https://management.azure.com/subscriptions/$($account.id)/resourceGroups/$ResourceGroupName/providers/Microsoft.Insights/dataCollectionRules/${dcrName}?api-version=2022-06-01"

try {
    $dcrResponse = Invoke-RestMethod -Uri $dcrUri -Method Put -Headers $headers -Body $dcrJson
    $dcrImmutableId = $dcrResponse.properties.immutableId
    $dcrResourceId = $dcrResponse.id
    Write-Host "  ✓ DCR created successfully" -ForegroundColor Green
    Write-Host "    DCR ID: $dcrImmutableId" -ForegroundColor White
} catch {
    Write-Host "  ✗ Failed to create DCR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Response: $($_.ErrorDetails.Message)" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Output summary
Write-Host "========================================================================================================" -ForegroundColor Cyan
Write-Host "DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "========================================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📋 Configuration Values (save these for the Python script):" -ForegroundColor Yellow
Write-Host ""
Write-Host "DCE_ENDPOINT = `"$dceEndpoint`"" -ForegroundColor White
Write-Host "DCR_ID = `"$dcrImmutableId`"" -ForegroundColor White
Write-Host "STREAM_NAME = `"$streamName`"" -ForegroundColor White
Write-Host ""
Write-Host "DCR Resource ID (for role assignment):" -ForegroundColor Yellow
Write-Host "$dcrResourceId" -ForegroundColor White
Write-Host ""
Write-Host "========================================================================================================" -ForegroundColor Cyan
Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host "========================================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Create Azure AD App Registration (see README.md)" -ForegroundColor White
Write-Host ""
Write-Host "2. Assign 'Monitoring Metrics Publisher' role to your App Registration:" -ForegroundColor White
Write-Host ""
Write-Host "   az role assignment create \" -ForegroundColor Gray
Write-Host "     --assignee <YOUR-APP-CLIENT-ID> \" -ForegroundColor Gray
Write-Host "     --role `"Monitoring Metrics Publisher`" \" -ForegroundColor Gray
Write-Host "     --scope `"$dcrResourceId`"" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Update eventhub_to_sentinel.py with the configuration values above" -ForegroundColor White
Write-Host ""
Write-Host "4. Run: python eventhub_to_sentinel.py" -ForegroundColor White
Write-Host ""
Write-Host "========================================================================================================" -ForegroundColor Cyan
