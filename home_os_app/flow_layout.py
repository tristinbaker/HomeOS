from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing if spacing >= 0 else self.spacing())
        self._item_list = []

    def __del__(self):
        while self._item_list:
            item = self._item_list.pop()
            self.removeItem(item)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def _do_layout(self, rect, only_height):
        m = self.contentsMargins()
        effective = rect.adjusted(+m.left(), +m.top(), -m.right(), -m.bottom())
        available_w = effective.width()
        y = effective.y()
        spacing = self.spacing()

        # Group items into rows first, then centre each row
        rows: list[list] = []
        current_row: list = []
        current_w = 0

        for item in self._item_list:
            item_w = item.sizeHint().width()
            needed = (spacing + item_w) if current_row else item_w
            if current_row and current_w + needed > available_w:
                rows.append(current_row)
                current_row = [item]
                current_w = item_w
            else:
                current_row.append(item)
                current_w += needed

        if current_row:
            rows.append(current_row)

        for row in rows:
            row_w = sum(it.sizeHint().width() for it in row) + spacing * (len(row) - 1)
            x = effective.x() + max(0, (available_w - row_w) // 2)
            line_height = 0
            for item in row:
                hint = item.sizeHint()
                if not only_height:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width() + spacing
                line_height = max(line_height, hint.height())
            y += line_height + spacing

        total_h = y - spacing - rect.y() + m.bottom() if rows else m.top() + m.bottom()
        return total_h
