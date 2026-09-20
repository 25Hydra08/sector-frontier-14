using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Grid_Debugger.Core;

namespace Grid_Debugger.Win
{
    public class MainForm : Form
    {
        private Button btnChooseFile = null!;
        private TextBox txtFile = null!;
        private Button btnChooseFolder = null!;
        private TextBox txtFolder = null!;
        private Button btnDebug = null!;
        private TextBox txtLog = null!;
        private ProgressBar progressBar = null!;

        private string? selectedFile;
        private string? selectedFolder;

        public MainForm()
        {
            Text = "Grid Debugger";
            Width = 900;
            Height = 600;

            InitializeComponents();
        }

        private void InitializeComponents()
        {
            btnChooseFile = new Button { Text = "Выбрать маппинг", Left = 10, Top = 10, Width = 240, Height = 36 };
            txtFile = new TextBox { Left = 10, Top = 52, Width = 520, ReadOnly = true };
            btnChooseFolder = new Button { Text = "Папка сохранения", Left = 10, Top = 88, Width = 240, Height = 36 };
            txtFolder = new TextBox { Left = 10, Top = 130, Width = 520, ReadOnly = true };
            btnDebug = new Button { Text = "Дебаг", Left = 10, Top = 168, Width = 240, Height = 40 };
            var btnSaveLogs = new Button { Text = "Сохранить логи", Left = 270, Top = 168, Width = 160, Height = 40 };
            progressBar = new ProgressBar { Left = 10, Top = 218, Width = 520, Height = 22 };

            txtLog = new TextBox { Left = 10, Top = 252, Width = 860, Height = 320, Multiline = true, ScrollBars = ScrollBars.Vertical, ReadOnly = true, WordWrap = false, Anchor = ((System.Windows.Forms.AnchorStyles)((((System.Windows.Forms.AnchorStyles.Top | System.Windows.Forms.AnchorStyles.Bottom)
                        | System.Windows.Forms.AnchorStyles.Left)
                        | System.Windows.Forms.AnchorStyles.Right))) };

            btnChooseFile.Click += BtnChooseFile_Click;
            btnChooseFolder.Click += BtnChooseFolder_Click;
            btnDebug.Click += BtnDebug_Click;
            btnSaveLogs.Click += (s, e) =>
            {
                using var dlg = new SaveFileDialog();
                dlg.Filter = "Text files (*.txt)|*.txt|All files (*.*)|*.*";
                if (dlg.ShowDialog() == DialogResult.OK)
                {
                    try
                    {
                        System.IO.File.WriteAllText(dlg.FileName, txtLog.Text);
                        Log($"Логи сохранены в: {dlg.FileName}");
                    }
                    catch (Exception ex)
                    {
                        Log($"Ошибка сохранения логов: {ex.Message}");
                    }
                }
            };

            Controls.Add(btnChooseFile);
            Controls.Add(txtFile);
            Controls.Add(btnChooseFolder);
            Controls.Add(txtFolder);
            Controls.Add(btnDebug);
            Controls.Add(btnSaveLogs);
            Controls.Add(progressBar);
            Controls.Add(txtLog);

            // make controls anchor to resize appropriately
            btnChooseFile.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            txtFile.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
            btnChooseFolder.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            txtFolder.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
            btnDebug.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            btnSaveLogs.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            progressBar.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
            txtLog.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        }

        private void Log(string s)
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action(() => Log(s)));
                return;
            }

            txtLog.AppendText($"[{DateTime.Now:HH:mm:ss}] {s}{Environment.NewLine}");
        }

        private void BtnChooseFile_Click(object? sender, EventArgs e)
        {
            using var dlg = new OpenFileDialog();
            dlg.Filter = "YAML files (*.yml;*.yaml)|*.yml;*.yaml|All files (*.*)|*.*";
            if (dlg.ShowDialog() == DialogResult.OK)
            {
                selectedFile = dlg.FileName;
                txtFile.Text = selectedFile;
                Log($"Выбран файл: {selectedFile}");
            }
        }

        private void BtnChooseFolder_Click(object? sender, EventArgs e)
        {
            using var dlg = new FolderBrowserDialog();
            if (dlg.ShowDialog() == DialogResult.OK)
            {
                selectedFolder = dlg.SelectedPath;
                txtFolder.Text = selectedFolder;
                Log($"Папка сохранения: {selectedFolder}");
            }
        }

        private async void BtnDebug_Click(object? sender, EventArgs e)
        {
            if (string.IsNullOrEmpty(selectedFile) || string.IsNullOrEmpty(selectedFolder))
            {
                Log("Выберите файл и папку сохранения");
                return;
            }

            btnDebug.Enabled = false;
            progressBar.Style = ProgressBarStyle.Marquee;
            Log("Запуск очистки...");

            var output = Path.Combine(selectedFolder!, Path.GetFileName(selectedFile!));

            try
            {
                var progress = new Progress<string>(s => Log(s));
                var result = await Orchestrator.RunCleanupAsync(selectedFile!, output, progress);
                var success = result.success;
                var message = result.message;
                Log($"Завершено: {message}");
            }
            catch (Exception ex)
            {
                Log($"Ошибка: {ex.Message}");
            }
            finally
            {
                progressBar.Style = ProgressBarStyle.Continuous;
                btnDebug.Enabled = true;
            }
        }
    }
}
