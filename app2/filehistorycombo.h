#ifndef FILEHISTORYCOMBO_H
#define FILEHISTORYCOMBO_H

#include <QComboBox>

class FileHistoryCombo : public QComboBox
{
    Q_OBJECT
public:
    FileHistoryCombo(QWidget *parent = nullptr);

    void setBaseDir(const QString& text);

    void setPlaceholderText(const QString& text);

private slots:
    void update_state(const QString &text);

private:
    QString mBaseDir{"."};
    QAction *mStatusAction{};
};

#endif // FILEHISTORYCOMBO_H
