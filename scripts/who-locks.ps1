# who-locks.ps1 -- 用 Windows Restart Manager 查"谁占着这个文件/目录"
# 用法: powershell -NoProfile -File who-locks.ps1 "D:\some\path"
# 原理: RmStartSession / RmRegisterResources / RmGetList（Vista+ 系统自带，无需第三方工具、无需管理员）
param([Parameter(Mandatory=$true)][string]$Path)
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$src = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class RmLock {
    [StructLayout(LayoutKind.Sequential)]
    struct RM_UNIQUE_PROCESS { public int dwProcessId; public System.Runtime.InteropServices.ComTypes.FILETIME ProcessStartTime; }

    const int CCH_RM_MAX_APP_NAME = 255;
    const int CCH_RM_MAX_SVC_NAME = 63;

    enum RM_APP_TYPE { RmUnknownApp = 0, RmMainWindow = 1, RmOtherWindow = 2, RmService = 3, RmExplorer = 4, RmConsole = 5, RmCritical = 1000 }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct RM_PROCESS_INFO {
        public RM_UNIQUE_PROCESS Process;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = CCH_RM_MAX_APP_NAME + 1)] public string strAppName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = CCH_RM_MAX_SVC_NAME + 1)] public string strServiceShortName;
        public RM_APP_TYPE ApplicationType;
        public uint AppStatus;
        public uint TSSessionId;
        [MarshalAs(UnmanagedType.Bool)] public bool bRestartable;
    }

    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
    static extern int RmRegisterResources(uint pSessionHandle, uint nFiles, string[] rgsFilenames,
        uint nApplications, [In] RM_UNIQUE_PROCESS[] rgApplications, uint nServices, string[] rgsServiceNames);

    [DllImport("rstrtmgr.dll", CharSet = CharSet.Auto)]
    static extern int RmStartSession(out uint pSessionHandle, int dwSessionFlags, string strSessionKey);

    [DllImport("rstrtmgr.dll")]
    static extern int RmEndSession(uint pSessionHandle);

    [DllImport("rstrtmgr.dll")]
    static extern int RmGetList(uint dwSessionHandle, out uint pnProcInfoNeeded, ref uint pnProcInfo,
        [In, Out] RM_PROCESS_INFO[] rgAffectedApps, ref uint lpdwRebootReasons);

    public static List<string> Who(string path) {
        uint handle; string key = Guid.NewGuid().ToString();
        var result = new List<string>();
        if (RmStartSession(out handle, 0, key) != 0) { result.Add("ERR: RmStartSession failed"); return result; }
        try {
            if (RmRegisterResources(handle, 1, new[] { path }, 0, null, 0, null) != 0) {
                result.Add("ERR: RmRegisterResources failed"); return result;
            }
            uint needed = 0, count = 0, reasons = 0;
            int rc = RmGetList(handle, out needed, ref count, null, ref reasons);
            if (rc == 234) {
                var arr = new RM_PROCESS_INFO[needed];
                count = needed;
                rc = RmGetList(handle, out needed, ref count, arr, ref reasons);
                if (rc == 0) {
                    for (int i = 0; i < count; i++) {
                        var p = arr[i];
                        result.Add(string.Format("{0}|{1}|{2}|{3}", p.Process.dwProcessId, p.strAppName,
                            p.ApplicationType, p.bRestartable));
                    }
                } else result.Add("ERR: RmGetList retry failed " + rc);
            } else if (rc != 0) result.Add("ERR: RmGetList failed " + rc);
        } finally { RmEndSession(handle); }
        return result;
    }
}
'@

if (-not ('RmLock' -as [type])) { Add-Type -TypeDefinition $src -Language CSharp | Out-Null }

$full = (Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue)
if (-not $full) { Write-Output "路径不存在: $Path"; exit 2 }

$rows = [RmLock]::Who($full.Path)
if ($rows.Count -eq 0) { Write-Output "没有进程占用: $($full.Path)"; exit 0 }
if ($rows[0] -like 'ERR:*') { Write-Output $rows[0]; exit 3 }

Write-Output "占用者（PID | 应用名 | 类型 | 可重启）:"
foreach ($r in $rows) {
    $f = $r.Split('|')
    $proc = Get-Process -Id $f[0] -ErrorAction SilentlyContinue
    $exe = if ($proc) { $proc.Path } else { '' }
    Write-Output ("  {0,-7} {1,-28} {2,-10} {3,-6} {4}" -f $f[0], $f[1], $f[2], $f[3], $exe)
}
exit 0
