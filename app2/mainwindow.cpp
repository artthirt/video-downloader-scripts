#include "mainwindow.h"
#include "ui_mainwindow.h"
#include "ffmpegdecoder.h"

#include <QMimeData>
#include <QFileDialog>
#include <QMessageBox>
#include <QClipboard>
#include <QApplication>
#include <QRegularExpression>
#include <QFileInfo>
#include <QUrl>
#include <QScrollBar>
#include <QTableWidget>
#include <QSettings>

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
    , ui(std::make_unique<Ui::MainWindow>())
    , m_decoder(new FFmpegDecoder(this))
{
    ui->setupUi(this);
    setupConnections();

    mCompleterOut.setModel(&mCompleterModel);
    ui->lineEditOutput->setCompleter(&mCompleterOut);
    
    // Setup decoder callbacks using Qt's signal/slot mechanism via invokeMethod
    m_decoder->onProgress = [this](const FFmpegDecoder::ProgressInfo &info) {
        QMetaObject::invokeMethod(this, [this, info]() {
            onProgress(info);
        }, Qt::QueuedConnection);
    };
    
    m_decoder->onLog = [this](const QString &msg) {
        QMetaObject::invokeMethod(this, [this, msg]() {
            onLog(msg);
        }, Qt::QueuedConnection);
    };
    
    m_decoder->onFinished = [this](bool success, const QString &msg) {
        QMetaObject::invokeMethod(this, [this, success, msg]() {
            onFinished(success, msg);
        }, Qt::QueuedConnection);
    };

    ui->history_table->setColumnCount(3);
    ui->history_table->setHorizontalHeaderLabels({"Output Name", "URL", "Status"});
    ui->history_table->horizontalHeader()->setStretchLastSection(true);
    ui->history_table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::ResizeMode::Stretch);
    ui->history_table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::ResizeMode::Stretch);
    ui->history_table->setSelectionBehavior(QTableWidget::SelectionBehavior::SelectRows);
    ui->history_table->setEditTriggers(QTableWidget::EditTrigger::NoEditTriggers);
    ui->history_table->setAlternatingRowColors(true);
    ui->history_table->setMinimumWidth(350);
    ui->history_table->setContextMenuPolicy(Qt::ContextMenuPolicy::CustomContextMenu);
    connect(ui->history_table, &QTableWidget::customContextMenuRequested, this, &MainWindow::show_context_menu);

    ui->splitter->setSizes({650, 350});

    loadSettings();
}

MainWindow::~MainWindow()
{
    saveSettings();

    ui.reset();
}

void MainWindow::setupConnections()
{
    //connect(ui->lineEditUrl, &QLineEdit::textChanged, this, &MainWindow::onUrlTextChanged);
    connect(ui->lineEditUrl, &QComboBox::currentTextChanged, this, &MainWindow::onUrlTextChanged);
    connect(ui->btnBrowse, &QPushButton::clicked, this, &MainWindow::onBrowseClicked);
    connect(ui->checkBoxCopy, &QCheckBox::stateChanged, this, &MainWindow::onCopyToggled);
    connect(ui->btnStart, &QPushButton::clicked, this, &MainWindow::onStartClicked);
    connect(ui->btnCancel, &QPushButton::clicked, this, &MainWindow::onCancelClicked);
    connect(ui->btnClear, &QPushButton::clicked, this, &MainWindow::onClearClicked);
    connect(ui->tbtClearListUrls, &QToolButton::clicked, this, [this](){
        if(QMessageBox::information(nullptr, "Clear list or url", "Are you sure?",
                                     QMessageBox::Ok | QMessageBox::Cancel) == QMessageBox::Ok)
        {
            ui->lineEditUrl->clear();
        }
    });
    auto action_copy_file = m_history_menu.addAction("Copy File Name");
    auto action_copy_ref = m_history_menu.addAction("Copy Reference");
    auto action_copy_to_file_place = m_history_menu.addAction("Copy File Name to Output");
    auto action_remove = m_history_menu.addAction("Remowe row");
    connect(action_copy_file, &QAction::triggered, this, &MainWindow::onActionCopyFileName);
    connect(action_copy_ref, &QAction::triggered, this, &MainWindow::onActionCopyReference);
    connect(action_copy_to_file_place, &QAction::triggered, this, &MainWindow::onActionCopyFileNameToOutput);
    connect(action_remove, &QAction::triggered, this, &MainWindow::onActionRemoveRow);
}

void MainWindow::suggestFilename()
{
    QString url = ui->lineEditUrl->currentText().trimmed();
    if (url.isEmpty()) return;
    
    QUrl qurl(url);
    QString path = qurl.path();
    QFileInfo info(path);
    QString name = info.baseName();
    
    if (!name.isEmpty() && name != "index" && name != "playlist" 
        && name != "master" && name != "stream") {
        QString suggested = name + ".mp4";
        if (ui->lineEditOutput->currentText().isEmpty()) {
            ui->lineEditOutput->setCurrentText(suggested);
        }
    }
}

void MainWindow::onUrlTextChanged(const QString &text)
{
    suggestFilename();
}

void MainWindow::onPasteClicked()
{
    QClipboard *clipboard = QApplication::clipboard();
    QString text = clipboard->text();
    if (!text.isEmpty()) {
        ui->lineEditUrl->setCurrentText(text);
        suggestFilename();
    }
}

void MainWindow::onBrowseClicked()
{
    QString filePath = QFileDialog::getSaveFileName(this, 
        "Save MP4 File", QString(), "MP4 Files (*.mp4);;All Files (*)");
    
    if (!filePath.isEmpty()) {
        if (!filePath.endsWith(".mp4", Qt::CaseInsensitive)) {
            filePath += ".mp4";
        }
        ui->lineEditOutput->setCurrentText(filePath);
    }
}

void MainWindow::onCopyToggled(int state)
{
    bool copyEnabled = (state == Qt::Checked);
    ui->spinBoxCRF->setEnabled(!copyEnabled);
    ui->comboBoxPreset->setEnabled(!copyEnabled);
    ui->comboBoxAudioFilter->setEnabled(copyEnabled);
}

bool MainWindow::validateInputs()
{
    QString url = ui->lineEditUrl->currentText().trimmed();
    QString output = ui->lineEditOutput->currentText().trimmed();
    
    if (url.isEmpty()) {
        QMessageBox::warning(this, "Input Error", "Please enter a valid M3U8 URL");
        return false;
    }
    
    if (output.isEmpty()) {
        ui->lineEditOutput->setCurrentText("output.mp4");
    }
    
    return true;
}

void MainWindow::loadSettings()
{
    QSettings settings;

    auto listUrls = settings.value("list_url").toStringList();
    ui->lineEditUrl->addItems(listUrls);

    auto listOuts = settings.value("list_out").toStringList();
    ui->lineEditOutput->addItems(listOuts);
    mCompleterModel.setStringList(listOuts);

    auto history_data = settings.value("download_history");
    if(history_data.typeId() == QVariant::List){
        ui->history_table->setRowCount(0);
        m_download_history.clear();

        for(const auto &item_data: history_data.toList()){
            auto item = DownloadHistoryItem::from_dict(item_data);
            if(item.status == "Downloading"){
                item.status = "Failed";
                item.progress = 0;
            }
            add_history_row(item.output, item.url, item.status);
        }
    }
}

QStringList saveToSett(QSettings& settings, QComboBox *cb, QString key)
{
    QStringList list;
    for(int i = 0; i < cb->count(); ++i){
        list << cb->itemText(i);
    }
    settings.setValue(key, list);
    return list;
}

void MainWindow::saveSettings()
{
    QSettings settings;

    saveToSett(settings, ui->lineEditUrl, "list_url");
    saveToSett(settings, ui->lineEditOutput, "list_out");

    if(1){
        QList<QVariant> history_data;
        for(auto item: m_download_history){
            history_data.push_back(item.to_dict());
        }
        settings.setValue("download_history", history_data);
    }
}

void MainWindow::addUrlToHistory(const QString &url)
{
    QStringList list;
    for(int i = 0; i < ui->lineEditUrl->count(); ++i){
        list << ui->lineEditUrl->itemText(i);
    }
    if(list.contains(url)){
        return;
    }
    list << url;
    ui->lineEditUrl->clear();
    ui->lineEditUrl->addItems(list);
    QEventLoop lp;
    lp.processEvents();
}

void MainWindow::addOutToHistory(const QString &url)
{
    QStringList list;
    for(int i = 0; i < ui->lineEditOutput->count(); ++i){
        list << ui->lineEditOutput->itemText(i);
    }
    if(list.contains(url)){
        return;
    }
    list << url;
    ui->lineEditOutput->clear();
    ui->lineEditOutput->addItems(list);
    mCompleterModel.setStringList(list);
    QEventLoop lp;
    lp.processEvents();
}

int MainWindow::add_history_row(const QString &output, const QString &url, const QString &status)
{
    DownloadHistoryItem hitem;
    hitem.output = output;
    hitem.url = url;
    hitem.status = status;

    for(int i = 0; i < m_download_history.size(); ++i){
        if(hitem.url == m_download_history[i].url && hitem.output == m_download_history[i].output){
            auto status_item = ui->history_table->item(i, 0);
            ui->history_table->scrollToItem(status_item);
            return i;
        }
    }

    auto row = ui->history_table->rowCount();
    ui->history_table->insertRow(row);

    auto name_item = new QTableWidgetItem(output);
    name_item->setToolTip(output);
    name_item->setData(Qt::UserRole, row);
    ui->history_table->setItem(row, 0, name_item);

    auto url_item = new QTableWidgetItem(url);
    url_item->setToolTip(url);
    ui->history_table->setItem(row, 1, url_item);

    auto status_item = new QTableWidgetItem(status);
    status_item->setToolTip(status);
    ui->history_table->setItem(row, 2, status_item);

    ui->history_table->scrollToItem(name_item);

    m_download_history.push_back(hitem);

    return row;
}

void MainWindow::update_history_status(int row, const QString &status)
{
    if(row >= 0 and row < ui->history_table->rowCount()){
        ui->history_table->item(row, 2)->setText(status);
        m_download_history[row].status = status;
    }
}

void MainWindow::clear_history()
{
    ui->history_table->setRowCount(0);
    m_download_history = {};
    m_current_row = -1;
}

void MainWindow::onStartClicked()
{
    if (!validateInputs()) return;
    
    QString url = ui->lineEditUrl->currentText().trimmed();
    QString output = ui->lineEditOutput->currentText().trimmed();
    addUrlToHistory(url);
    addOutToHistory(output);
    saveSettings();
    
    ui->plainTextEditLog->clear();
    ui->plainTextEditLog->appendPlainText(QString("Input: %1\n").arg(url));
    ui->plainTextEditLog->appendPlainText(QString("Output: %1\n").arg(output));
    ui->plainTextEditLog->appendPlainText("Initializing FFmpeg...\n");
    
    // Initialize decoder
    if (!m_decoder->initialize(url, output)) {
        QMessageBox::critical(this, "Error", "Failed to initialize FFmpeg decoder");
        return;
    }
    
    ui->progressBar->setValue(0);
    ui->btnStart->setEnabled(false);
    ui->btnCancel->setEnabled(true);
    ui->lineEditUrl->setEnabled(false);
    ui->lineEditOutput->setEnabled(false);

    m_current_row = add_history_row(output, url, "Downloading...");
    
    m_decoder->start();
}

void MainWindow::onCancelClicked()
{
    ui->statusBar->showMessage("Cancelling...");
    m_decoder->stop();
    if(m_current_row >= 0){
        update_history_status(m_current_row, "Canceled");
    }
}

void MainWindow::onClearClicked()
{
    ui->plainTextEditLog->clear();
}

void MainWindow::onProgress(const FFmpegDecoder::ProgressInfo &info)
{
    if (info.totalDuration > 0) {
        int percent = qMin(100, int((info.currentTime / info.totalDuration) * 100));
        ui->progressBar->setValue(percent);
        ui->statusBar->showMessage(QString("Downloading: %1% (Frame %2, %3fps)")
            .arg(percent)
            .arg(info.frameCount)
            .arg(info.fps, 0, 'f', 1));
        if(m_current_row >= 0){
            update_history_status(m_current_row, QString("Downloading... %1%").arg(percent));
        }
    } else {
        ui->statusBar->showMessage(QString("Downloading... Frame %1").arg(info.frameCount));
    }
}

void MainWindow::onLog(const QString &text)
{
    ui->plainTextEditLog->appendPlainText(text + "\n");
    QScrollBar *sb = ui->plainTextEditLog->verticalScrollBar();
    sb->setValue(sb->maximum());
}

void MainWindow::onFinished(bool success, const QString &message)
{
    ui->btnStart->setEnabled(true);
    ui->btnCancel->setEnabled(false);
    ui->lineEditUrl->setEnabled(true);
    ui->lineEditOutput->setEnabled(true);
    
    if (success) {
        ui->progressBar->setValue(100);
        QMessageBox::information(this, "Success", message);
        if(m_current_row >= 0){
            update_history_status(m_current_row, "Downloaded");
        }
    } else {
        ui->progressBar->setValue(0);
        QMessageBox::warning(this, "Download Status", message);
        if(m_current_row >= 0){
            update_history_status(m_current_row, QString("Failed: %1").arg(message));
        }
    }
    
    ui->statusBar->showMessage(message);
}

void MainWindow::show_context_menu(const QPoint &pos)
{
    auto item = ui->history_table->itemAt(pos);
    if(!item){
        return;
    }
    m_history_row = item->row();

    m_history_menu.popup(ui->history_table->viewport()->mapToGlobal(pos));
}

void MainWindow::onActionRemoveRow(bool)
{
    if(m_history_row < m_download_history.size()){
        m_download_history.removeAt(m_history_row);
        ui->history_table->removeRow(m_history_row);
    }
}

void MainWindow::onActionCopyFileName(bool)
{
    if(m_history_row < m_download_history.size()){
        auto name = m_download_history[m_history_row].output;
        qApp->clipboard()->setText(name);
    }
}

void MainWindow::onActionCopyReference(bool)
{
    if(m_history_row < m_download_history.size()){
        auto name = m_download_history[m_history_row].url;
        qApp->clipboard()->setText(name);
    }
}

void MainWindow::onActionCopyFileNameToOutput(bool)
{
    if(m_history_row < m_download_history.size()){
        auto name = m_download_history[m_history_row].output;
        ui->lineEditOutput->setCurrentText(name);
    }
}

void MainWindow::on_tbtPastFromClipboard_clicked()
{
    auto clip = qApp->clipboard();
    auto md = clip->mimeData();
    if(md->hasText()){
        ui->lineEditUrl->setCurrentText(md->text());
    }
}

void MainWindow::on_tbtClearListOutput_clicked()
{
    ui->lineEditOutput->setCurrentText("");
}