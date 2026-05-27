#include "filehistorycombo.h"

#include <QDir>
#include <QFileInfo>
#include <QLineEdit>

FileHistoryCombo::FileHistoryCombo(QWidget *parent)
    : QComboBox(parent)
{
    setEditable(true);
    setInsertPolicy(InsertAtTop);

    mStatusAction = lineEdit()->addAction(
        style()->standardIcon(QStyle::SP_MessageBoxInformation),
        lineEdit()->TrailingPosition);

    connect(lineEdit(), &QLineEdit::textChanged, this, &FileHistoryCombo::update_state);

    update_state(currentText());
}

void FileHistoryCombo::setBaseDir(const QString &text)
{
    mBaseDir = text;
}

void FileHistoryCombo::setPlaceholderText(const QString &text)
{
    if(lineEdit()){
        lineEdit()->setPlaceholderText(text);
    }else{
        QComboBox::setPlaceholderText(text);
    }
}

void FileHistoryCombo::update_state(const QString &text)
{
    bool valid = !text.isEmpty() && !text.contains("/") && !text.contains("\\");

    if(!valid){
        lineEdit()->setStyleSheet("QLineEdit { border: 2px solid gray; }");

        mStatusAction->setIcon(style()->standardIcon(QStyle::SP_MessageBoxWarning));
        setToolTip("Invalid file name");
        return;
    }

    QDir bd(mBaseDir);
    QString full_path = QFileInfo(bd, text).absoluteFilePath();

    if(QFile::exists(full_path)){
        lineEdit()->setStyleSheet("QLineEdit { border: 2px solid red; }");

        mStatusAction->setIcon(style()->standardIcon(QStyle::SP_DialogCancelButton));
        setToolTip("File already exists");
    }else{
        lineEdit()->setStyleSheet("QLineEdit { border: 2px solid green; }");

        mStatusAction->setIcon(style()->standardIcon(QStyle::SP_DialogApplyButton));
        setToolTip("File name is available");
    }
}
