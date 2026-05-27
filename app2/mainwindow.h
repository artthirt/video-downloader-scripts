#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QCompleter>
#include <QMenu>
#include <QStringListModel>
#include <memory>

#include "ffmpegdecoder.h"

QT_BEGIN_NAMESPACE
namespace Ui { class MainWindow; }
QT_END_NAMESPACE

class FFmpegDecoder;
class QTableWidget;

class DownloadHistoryItem{
public:
    QString url;
    QString output;
    QString status;
    float progress{};
    int64_t timestamp{};

    QVariantMap to_dict() const {
        return {
            {"url", url},
            {"output", output},
            {"status", status},
            {"progress", progress},
            {"timestamp", timestamp},
        };
    }
    static DownloadHistoryItem from_dict(QVariant v){
        if(v.typeId() != QVariant::Map){
            return {};
        }
        auto m = v.toMap();
        DownloadHistoryItem r;
        r.url = m["url"].toString();
        r.output = m["output"].toString();
        r.status = m["status"].toString();
        r.progress = m["progress"].toFloat();
        r.timestamp = m["timestamp"].toLongLong();
        return r;
    }
};

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    MainWindow(QWidget *parent = nullptr);
    ~MainWindow();

private slots:
    void onUrlTextChanged(const QString &text);
    void onPasteClicked();
    void onBrowseClicked();
    void onCopyToggled(int state);
    void onStartClicked();
    void onCancelClicked();
    void onClearClicked();
    void onProgress(const FFmpegDecoder::ProgressInfo &info);
    void onLog(const QString &text);
    void onFinished(bool success, const QString &message);
    void show_context_menu(const QPoint& pos);
    void onActionRemoveRow(bool);
    void onActionCopyFileName(bool);
    void onActionCopyReference(bool);
    void onActionCopyFileNameToOutput(bool);

    void on_tbtPastFromClipboard_clicked();
    void on_tbtClearListOutput_clicked();

private:
    void setupConnections();
    void suggestFilename();
    bool validateInputs();

    void loadSettings();
    void saveSettings();

    void addUrlToHistory(const QString& url);
    void addOutToHistory(const QString& url);
    int add_history_row(const QString& output, const QString& url, const QString& status);

    void update_history_status(int row, const QString& status);
    void clear_history();

    std::unique_ptr<Ui::MainWindow> ui;
    FFmpegDecoder *m_decoder{};

    QList<DownloadHistoryItem> m_download_history;
    QMenu m_history_menu;
    int m_history_row{};
    int m_current_row{-1};

    QCompleter mCompleterOut;
    QStringListModel mCompleterModel;
};

#endif // MAINWINDOW_H