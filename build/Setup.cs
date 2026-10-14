using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

static class Setup
{
    const string Title = "Desktop Focus";

    static void Extract(string resource, string path)
    {
        using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream(resource))
        using (FileStream f = new FileStream(path, FileMode.Create, FileAccess.Write))
        {
            s.CopyTo(f);
        }
    }

    [STAThread]
    static int Main()
    {
        try
        {
            string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Programs\DesktopFocus");
            string exe = Path.Combine(dir, "DesktopFocus.exe");

            foreach (Process p in Process.GetProcessesByName("DesktopFocus"))
            {
                try { p.Kill(); p.WaitForExit(3000); } catch { }
            }

            Directory.CreateDirectory(dir);
            Extract("DesktopFocus.exe", exe);
            Extract("uninstall.ps1", Path.Combine(dir, "uninstall.ps1"));

            string lnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Desktop Focus.lnk");
            Type t = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(t);
            object sc = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { lnk });
            Type st = sc.GetType();
            st.InvokeMember("TargetPath", BindingFlags.SetProperty, null, sc, new object[] { exe });
            st.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, sc, new object[] { dir });
            st.InvokeMember("Description", BindingFlags.SetProperty, null, sc, new object[] { "Скрыть иконки рабочего стола, кроме нужных" });
            st.InvokeMember("Save", BindingFlags.InvokeMethod, null, sc, null);

            using (RegistryKey k = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\DesktopFocus"))
            {
                k.SetValue("DisplayName", Title);
                k.SetValue("DisplayVersion", "1.0");
                k.SetValue("Publisher", "Fedor");
                k.SetValue("InstallLocation", dir);
                k.SetValue("DisplayIcon", exe);
                k.SetValue("UninstallString", "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + Path.Combine(dir, "uninstall.ps1") + "\"");
                k.SetValue("NoModify", 1, RegistryValueKind.DWord);
                k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }

            DialogResult r = MessageBox.Show("Desktop Focus установлен.\n\nЗапуск: меню Пуск -> Desktop Focus.\n\nЗапустить сейчас?",
                Title, MessageBoxButtons.YesNo, MessageBoxIcon.Information);
            if (r == DialogResult.Yes)
            {
                ProcessStartInfo psi = new ProcessStartInfo(exe);
                psi.WorkingDirectory = dir;
                psi.UseShellExecute = true;
                Process.Start(psi);
            }
            return 0;
        }
        catch (Exception e)
        {
            MessageBox.Show("Ошибка установки:\n" + e.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
