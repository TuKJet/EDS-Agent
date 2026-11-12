[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $ConfigPath,
    [Parameter(Mandatory)] [string] $OutputPath,
    [string] $ToolName,
    [string] $ArgumentsPath,
    [switch] $Discover,
    [ValidateRange(1,3600)] [int] $TimeoutSeconds = 120,
    [string] $StudyRoot,
    [string] $ExperimentRef,
    [string[]] $InputRefs = @(),
    [string] $BindingPath,
    [string] $Capability
)

$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $config.python_path -PathType Leaf)) { throw 'Configured MCP Python runtime is missing' }
$previous = $env:EDS_MCP_TOKEN
$secure = $null
try {
    $credentialPath = [string]$config.token_credential_path
    if ([string]::IsNullOrWhiteSpace($credentialPath)) {
        Remove-Item Env:\EDS_MCP_TOKEN -ErrorAction SilentlyContinue
    } else {
        $secure = Import-Clixml -LiteralPath $credentialPath
        if ($secure -isnot [Security.SecureString]) { throw 'Token credential must contain a DPAPI SecureString' }
        $env:EDS_MCP_TOKEN = [Net.NetworkCredential]::new('', $secure).Password
    }
    $clientArgs = @('-B','-X','utf8',(Join-Path $PSScriptRoot 'mcp_call.py'),
        '--url',[string]$config.url,'--timeout',[string]$TimeoutSeconds,'--output',$OutputPath)
    if ($config.expected_server) { $clientArgs += @('--expected-server',[string]$config.expected_server) }
    if ([bool]$BindingPath -ne [bool]$Capability) { throw 'BindingPath and Capability are required together' }
    if ($BindingPath) { $clientArgs += @('--binding',$BindingPath,'--capability',$Capability) }
    if ($Discover) {
        $clientArgs += 'discover'
    } else {
        if (-not $ToolName -or -not $ArgumentsPath) { throw 'ToolName and ArgumentsPath are required for one tool call' }
        if ($StudyRoot) {
            if (-not $ExperimentRef) { throw 'ExperimentRef is required with StudyRoot' }
            $clientArgs += @('--study-root',$StudyRoot,'--experiment-ref',$ExperimentRef)
            foreach ($inputRef in $InputRefs) { $clientArgs += @('--input-ref',$inputRef) }
        }
        $clientArgs += @('call',$ToolName,'--data',$ArgumentsPath)
    }
    & $config.python_path @clientArgs
    $edsResult = $LASTEXITCODE
} finally {
    if ($null -eq $previous) { Remove-Item Env:\EDS_MCP_TOKEN -ErrorAction SilentlyContinue }
    else { $env:EDS_MCP_TOKEN = $previous }
    $secure = $null
    $previous = $null
}
exit $edsResult
