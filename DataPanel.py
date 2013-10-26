# standard libraries
import copy
import gettext
import logging
import os
import random
import uuid
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import DataItem
from nion.swift.Decorators import queue_main_thread
from nion.swift import DataGroup
from nion.swift import Graphics
from nion.swift import Image
from nion.swift import Panel
from nion.swift import UserInterface

_ = gettext.gettext


"""
    When the user changes image panels, the data panel must update itself to reflect what
    is selected in the image panel. It does this by receiving the selected_image_panel_changed
    message.

    When the user selects a new data item or group, the data panel must notify the selected
    image panel. It does this in the itemChanged method.
"""


# TODO: The selection will change when the user changes focused image panel
# TODO: If the user selects a different data item, it needs to be associated with focused image panel
# TODO: Data panel has two selections: a folder and a data item
# TODO: Each folder remembers its data item selection (or has an algorithm if selected item was deleted)
# TODO: User can delete items from just that folder (delete), or from all folders (shift-delete)
# TODO: Image panel should retain the folder/data item combination, not just the data item.
# TODO: User needs to be able to select folder. But what happens when they do?
#       What if image panel selection becomes just a folder, it displays a blank, but retains the selection
# TODO: What happens when a group/item selected in a different image panel is deleted?

"""
    User clicks on data item -> update data_panel_selection, highlight data group and data item
    User clicks on data group -> highlight data group, highlight data item if data_panel_selection matches data group
    User switches image panels -> highlight data group and data item to match new data_panel_selection
"""


class DataPanel(Panel.Panel):

    # a tree model of the data groups. this class watches for changes to the data groups contained in the document controller
    # and responds by updating the item model controller associated with the data group tree view widget. it also handles
    # drag and drop and keeps the current selection synchronized with the image panel.

    class DataGroupModelController(object):

        def __init__(self, document_controller):
            self.ui = document_controller.ui
            self.item_model_controller = self.ui.create_item_model_controller(["display", "edit"])
            self.item_model_controller.on_item_set_data = lambda data, index, parent_row, parent_id: self.item_set_data(data, index, parent_row, parent_id)
            self.item_model_controller.on_item_drop_mime_data = lambda mime_data, action, row, parent_row, parent_id: self.item_drop_mime_data(mime_data, action, row, parent_row, parent_id)
            self.item_model_controller.on_item_mime_data = lambda row, parent_row, parent_id: self.item_mime_data(row, parent_row, parent_id)
            self.item_model_controller.on_remove_rows = lambda row, count, parent_row, parent_id: self.remove_rows(row, count, parent_row, parent_id)
            self.item_model_controller.supported_drop_actions = self.item_model_controller.DRAG | self.item_model_controller.DROP
            self.item_model_controller.mime_types_for_drop = ["text/uri-list", "text/data_item_uuid", "text/data_group_uuid"]
            self.__document_controller_weakref = weakref.ref(document_controller)
            self.document_controller.document_model.add_observer(self)
            self.__mapping = { document_controller.document_model: self.item_model_controller.root }
            self.on_receive_files = None
            # add items that already exist
            data_groups = document_controller.document_model.data_groups
            for index, data_group in enumerate(data_groups):
                self.item_inserted(document_controller.document_model, "data_groups", data_group, index)

        def close(self):
            # cheap way to unlisten to everything
            for object in self.__mapping.keys():
                if isinstance(object, DataGroup.DataGroup) or isinstance(object, DataGroup.SmartDataGroup):
                    object.remove_listener(self)
                    object.remove_observer(self)
                    object.remove_ref()
            self.document_controller.document_model.remove_observer(self)
            self.item_model_controller.close()
            self.item_model_controller = None

        def log(self, parent_id=-1, indent=""):
            parent_id = parent_id if parent_id >= 0 else self.item_model_controller.root.id
            for index, child in enumerate(self.item_model_controller.item_from_id(parent_id).children):
                value = child.data["display"] if "display" in child.data else "---"
                logging.debug(indent + str(index) + ": (" + str(child.id) + ") " + value)
                self.log(child.id, indent + "  ")

        def __get_document_controller(self):
            return self.__document_controller_weakref()
        document_controller = property(__get_document_controller)

        # these two methods support the 'count' display for data groups. they count up
        # the data items that are children of the container (which can be a data group
        # or a document controller) and also data items in all of their child groups.
        def __append_data_item_flat(self, container, data_items):
            if isinstance(container, DataItem.DataItem):
                data_items.append(container)
            for child_data_item in container.data_items:
                self.__append_data_item_flat(child_data_item, data_items)
        def __get_data_item_count_flat(self, container):
            data_items = []
            self.__append_data_item_flat(container, data_items)
            return len(data_items)

        # this message is received when a data item is inserted into one of the
        # groups we're observing.
        def item_inserted(self, container, key, object, before_index):
            if key == "data_groups":
                # manage the item model
                parent_item = self.__mapping[container]
                self.item_model_controller.begin_insert(before_index, before_index, parent_item.row, parent_item.id)
                count = self.__get_data_item_count_flat(object)
                properties = {
                    "display": str(object) + (" (%i)" % count),
                    "edit": object.title,
                    "data_group": object
                }
                item = self.item_model_controller.create_item(properties)
                parent_item.insert_child(before_index, item)
                self.__mapping[object] = item
                object.add_observer(self)
                object.add_listener(self)
                object.add_ref()
                self.item_model_controller.end_insert()
                # recursively insert items that already exist
                data_groups = object.data_groups
                for index, child_data_group in enumerate(data_groups):
                    self.item_inserted(object, "data_groups", child_data_group, index)

        # this message is received when a data item is removed from one of the
        # groups we're observing.
        def item_removed(self, container, key, object, index):
            if key == "data_groups":
                assert isinstance(object, DataGroup.DataGroup) or isinstance(object, DataGroup.SmartDataGroup)
                # get parent and item
                parent_item = self.__mapping[container]
                # manage the item model
                self.item_model_controller.begin_remove(index, index, parent_item.row, parent_item.id)
                object.remove_listener(self)
                object.remove_observer(self)
                object.remove_ref()
                parent_item.remove_child(parent_item.children[index])
                self.__mapping.pop(object)
                self.item_model_controller.end_remove()

        def __update_item_count(self, data_group):
            assert isinstance(data_group, DataGroup.DataGroup) or isinstance(data_group, DataGroup.SmartDataGroup)
            count = self.__get_data_item_count_flat(data_group)
            item = self.__mapping[data_group]
            item.data["display"] = str(data_group) + (" (%i)" % count)
            item.data["edit"] = data_group.title
            self.item_model_controller.data_changed(item.row, item.parent.row, item.parent.id)

        def property_changed(self, data_group, key, value):
            if key == "title":
                self.__update_item_count(data_group)

        # this method if called when one of our listened to data groups changes
        def data_item_inserted(self, container, data_item, before_index):
            self.__update_item_count(container)

        # this method if called when one of our listened to data groups changes
        def data_item_removed(self, container, data_item, index):
            self.__update_item_count(container)

        def item_set_data(self, data, index, parent_row, parent_id):
            data_group = self.item_model_controller.item_value("data_group", index, parent_id)
            if data_group:
                data_group.title = data
                return True
            return False

        def get_data_group(self, index, parent_row, parent_id):
            return self.item_model_controller.item_value("data_group", index, parent_id)

        def get_data_group_of_parent(self, parent_row, parent_id):
            parent_item = self.item_model_controller.item_from_id(parent_id)
            return parent_item.data["data_group"] if "data_group" in parent_item.data else None

        def get_data_group_index(self, data_group):
            item = None
            data_group_item = self.__mapping.get(data_group)
            parent_item = data_group_item.parent if data_group_item else self.item_model_controller.root
            assert parent_item is not None
            for child in parent_item.children:
                child_data_group = child.data.get("data_group")
                if child_data_group == data_group:
                    item = child
                    break
            if item:
                return item.row, item.parent.row, item.parent.id
            else:
                return -1, -1, 0

        def item_drop_mime_data(self, mime_data, action, row, parent_row, parent_id):
            data_group = self.get_data_group_of_parent(parent_row, parent_id)
            container = self.document_controller.document_model if parent_row < 0 and parent_id == 0 else data_group
            if data_group and mime_data.has_file_paths:
                if row >= 0:  # only accept drops ONTO items, not BETWEEN items
                    return self.item_model_controller.NONE
                if self.on_receive_files and self.on_receive_files(data_group, len(data_group.data_items), mime_data.file_paths):
                    return self.item_model_controller.COPY
            if data_group and mime_data.has_format("text/data_item_uuid"):
                if row >= 0:  # only accept drops ONTO items, not BETWEEN items
                    return self.item_model_controller.NONE
                # if the data item exists in this document, then it is copied to the
                # target group. if it doesn't exist in this document, then it is coming
                # from another document and can't be handled here.
                data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
                data_item = self.document_controller.document_model.get_data_item_by_key(data_item_uuid)
                if data_item:
                    data_item_copy = copy.deepcopy(data_item)
                    data_group.data_items.append(data_item_copy)
                    return action
                return self.item_model_controller.NONE
            if mime_data.has_format("text/data_group_uuid"):
                data_group_uuid = uuid.UUID(mime_data.data_as_string("text/data_group_uuid"))
                data_group = self.document_controller.document_model.get_data_group_by_uuid(data_group_uuid)
                if data_group:
                    data_group_copy = copy.deepcopy(data_group)
                    if row >= 0:
                        container.data_groups.insert(row, data_group_copy)
                    else:
                        container.data_groups.append(data_group_copy)
                    return action
            return self.item_model_controller.NONE

        def item_mime_data(self, index, parent_row, parent_id):
            data_group = self.get_data_group(index, parent_row, parent_id)
            if data_group:
                mime_data = self.ui.create_mime_data()
                mime_data.set_data_as_string("text/data_group_uuid", str(data_group.uuid))
                return mime_data
            return None

        def remove_rows(self, row, count, parent_row, parent_id):
            data_group = self.get_data_group_of_parent(parent_row, parent_id)
            container = self.document_controller.document_model if parent_row < 0 and parent_id == 0 else data_group
            for i in range(count):
                del container.data_groups[row]
            return True

    # a list model of the data items. data items are actually hierarchical in nature,
    # but we don't use a tree view since the hierarchy is always visible and represented
    # by indent level. this means that we must track changes to the data group that we're
    # inspecting and translate the hierarchy into a linear indexing scheme.
    class DataItemModelController(object):

        def __init__(self, document_controller):
            self.ui = document_controller.ui
            self.list_model_controller = self.ui.create_list_model_controller(["uuid", "level", "display", "display2"])
            self.list_model_controller.on_item_drop_mime_data = lambda mime_data, action, row, parent_row: self.item_drop_mime_data(mime_data, action, row, parent_row)
            self.list_model_controller.on_item_mime_data = lambda row: self.item_mime_data(row)
            self.list_model_controller.on_remove_rows = lambda row, count: self.remove_rows(row, count)
            self.list_model_controller.supported_drop_actions = self.list_model_controller.DRAG | self.list_model_controller.DROP
            self.list_model_controller.mime_types_for_drop = ["text/uri-list", "text/data_item_uuid"]
            self.__document_controller_weakref = weakref.ref(document_controller)
            self.__data_group = None
            self.on_receive_files = None

        def close(self):
            self.data_group = None
            self.list_model_controller.close()
            self.list_model_controller = None

        # used for queue_main_thread decorator
        delay_queue = property(lambda self: self.document_controller.delay_queue)

        def __get_document_controller(self):
            return self.__document_controller_weakref()
        document_controller = property(__get_document_controller)

        def __append_data_item_flat(self, data_item, data_items):
            data_items.append(data_item)
            for child_data_item in data_item.data_items:
                self.__append_data_item_flat(child_data_item, data_items)

        def get_data_items_flat(self):
            data_items = []
            if self.data_group:
                for data_item in self.data_group.data_items:
                    self.__append_data_item_flat(data_item, data_items)
            return data_items

        def __get_data_item_count_flat(self, data_item):
            data_items = []
            self.__append_data_item_flat(data_item, data_items)
            return len(data_items)

        # return a dict with key value pairs
        def get_model_data(self, index):
            return self.list_model_controller.model[index]
        def get_model_data_count(self):
            return len(self.list_model_controller.model)

        # this method if called when one of our listened to items changes
        def data_item_inserted(self, container, data_item, before_index):
            data_items_flat = self.get_data_items_flat()
            before_data_item = container.get_storage_relationship("data_items", before_index)
            before_index_flat = data_items_flat.index(before_data_item)
            level = self.list_model_controller.model[data_items_flat.index(container)]["level"]+1 if container in data_items_flat else 0
            # add the listener. this will result in calls to data_item_changed
            data_item.add_listener(self)
            # begin observing
            data_item.add_observer(self)
            data_item.add_ref()
            # do the insert
            data_shape = data_item.data_shape if data_item else None
            data_shape_str = " x ".join([str(d) for d in data_shape]) if data_shape else ""
            properties = {"uuid": str(data_item.uuid), "level": level, "display": str(data_item), "display2": data_shape_str}
            self.list_model_controller.begin_insert(before_index_flat, before_index_flat)
            self.list_model_controller.model.insert(before_index_flat, properties)
            self.list_model_controller.end_insert()
            # recursively insert items that already exist
            for index, child_data_item in enumerate(data_item.data_items):
                self.data_item_inserted(data_item, child_data_item, index)

        # this method if called when one of our listened to items changes
        def data_item_removed(self, container, data_item, index):
            assert isinstance(data_item, DataItem.DataItem)
            # recursively remove child items
            for index in reversed(range(len(data_item.data_items))):
                self.data_item_removed(data_item, data_item.data_items[index], index)
            # now figure out which index was removed
            index_flat = 0
            for item in self.list_model_controller.model:
                if uuid.UUID(item["uuid"]) == data_item.uuid:
                    break
                index_flat = index_flat + 1
            assert index_flat < len(self.list_model_controller.model)
            # manage the item model
            self.list_model_controller.begin_remove(index_flat, index_flat)
            del self.list_model_controller.model[index_flat]
            self.list_model_controller.end_remove()
            # remove the listener.
            data_item.remove_listener(self)
            # remove the observer.
            data_item.remove_observer(self)
            data_item.remove_ref()

        # data_item_changed is received from data items tracked in this model.
        # the connection is established in add_data_item using add_listener.
        @queue_main_thread
        def data_item_changed(self, data_item, info):
            data_items_flat = self.get_data_items_flat()
            # we might be receiving this message for an item that is no longer in the list
            # if the item updates and the user switches panels. check and skip it if so.
            if data_item in data_items_flat:
                index = data_items_flat.index(data_item)
                properties = self.list_model_controller.model[index]
                self.list_model_controller.data_changed()

        # determine the container for the data item. this is needed because the container
        # will not always be the data group that is being currently displayed. for instance,
        # the data item might be a processed data item and the container would be the
        # source data item. this is a recursive function, so pass the container in which
        # to search as first parameter.
        def get_data_item_container(self, container, query_data_item):
            if hasattr(container, "data_items") and query_data_item in container.data_items:
                return container
            if hasattr(container, "data_groups"):
                for data_group in container.data_groups:
                    container = self.get_data_item_container(data_group, query_data_item)
                    if container:
                        return container
            if hasattr(container, "data_items"):
                for data_item in container.data_items:
                    container = self.get_data_item_container(data_item, query_data_item)
                    if container:
                        return container
            return None

        def __get_data_group(self):
            return self.__data_group
        def __set_data_group(self, data_group):
            if data_group != self.__data_group:
                if self.__data_group:
                    # no longer watch for changes
                    self.__data_group.remove_listener(self)
                    # remove existing items
                    data_items = self.__data_group.data_items
                    for index in reversed(range(len(data_items))):
                        self.data_item_removed(self.__data_group, data_items[index], index)
                self.__data_group = data_group
                if self.__data_group:
                    # add new items
                    for index, child_data_item in enumerate(self.__data_group.data_items):
                        self.data_item_inserted(self.__data_group, child_data_item, index)
                    # watch fo changes
                    self.__data_group.add_listener(self)
        data_group = property(__get_data_group, __set_data_group)

        def get_data_item_index(self, data_item):
            data_items_flat = self.get_data_items_flat()
            index = data_items_flat.index(data_item) if data_item in data_items_flat else -1
            return index

        def item_drop_mime_data(self, mime_data, action, row, parent_row):
            if mime_data.has_file_paths:
                if self.on_receive_files and self.on_receive_files(mime_data.file_paths, row, parent_row):
                    return self.list_model_controller.COPY
            if mime_data.has_format("text/data_item_uuid") and parent_row < 0:
                data_group = self.data_group
                # don't allow copying of items in smart groups
                if data_group and isinstance(data_group, DataGroup.DataGroup):
                    data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
                    data_item = self.document_controller.document_model.get_data_item_by_key(data_item_uuid)
                    if data_item:
                        data_item_copy = copy.deepcopy(data_item)
                        if row >= 0:
                            data_group.data_items.insert(row, data_item_copy)
                        else:
                            data_group.data_items.append(data_item_copy)
                        return action
            return self.list_model_controller.NONE

        def item_mime_data(self, row):
            data_item = self.get_data_items_flat()[row] if row >= 0 else None
            if data_item:
                mime_data = self.ui.create_mime_data()
                mime_data.set_data_as_string("text/data_item_uuid", str(data_item.uuid))
                return mime_data
            return None

        def remove_rows(self, row, count):
            data_group = self.data_group
            # don't allow removal of rows in smart groups
            if data_group and isinstance(data_group, DataGroup.DataGroup):
                assert count == 1  # until implemented
                data_item = self.get_data_items_flat()[row] if row >= 0 else None
                if data_item:
                    data_group.data_items.remove(data_item)
            return True

        # this message comes from the styled item delegate
        def paint(self, ctx, options):
            rect = ((options["rect"]["top"], options["rect"]["left"]), (options["rect"]["height"], options["rect"]["width"]))
            index = options["index"]["row"]
            data_item = self.get_data_items_flat()[index]
            thumbnail_data = data_item.get_thumbnail_data(72, 72)
            data = self.get_model_data(index)
            level = data["level"]
            display = data["display"]
            display2 = data["display2"]
            ctx.save()
            if thumbnail_data is not None:
                draw_rect = ((rect[0][0] + 4, rect[0][1] + 4 + level * 16), (72, 72))
                draw_rect = Graphics.fit_to_size(draw_rect, thumbnail_data.shape)
                ctx.draw_image(thumbnail_data, draw_rect[0][1], draw_rect[0][0], draw_rect[1][1], draw_rect[1][0])
            ctx.fill_style = "#000"
            ctx.fill_text(display, rect[0][1] + 4 + level * 16 + 72 + 4, rect[0][0] + 4 + 17)
            ctx.font = "italic"
            ctx.fill_text(display2, rect[0][1] + 4 + level * 16 + 72 + 4, rect[0][0] + 4 + 17 + 17)
            ctx.restore()

    def __init__(self, document_controller, panel_id, properties):
        super(DataPanel, self).__init__(document_controller, panel_id, _("Data Items"))

        self.data_group_model_controller = DataPanel.DataGroupModelController(document_controller)
        self.data_group_model_controller.on_receive_files = lambda data_group, index, file_paths: self.data_group_model_receive_files(data_group, index, file_paths)

        self.data_item_model_controller = DataPanel.DataItemModelController(document_controller)

        def data_item_model_receive_files(file_paths, row, parent_row):
            data_group = self.data_item_model_controller.data_group
            if parent_row == -1:  # don't accept drops _on top_ of other items
                # row=-1, parent=-1 means dropping outside of any items; so put it at the end
                row = row if row >= 0 else len(data_group.data_items)
                return self.data_group_model_receive_files(data_group, row, file_paths)
            else:
                return False

        self.data_item_model_controller.on_receive_files = data_item_model_receive_files

        ui = document_controller.ui

        def data_group_widget_current_item_changed(index, parent_row, parent_id):
            saved_block1 = self.__block1
            self.__block1 = True
            data_group = self.data_group_model_controller.get_data_group(index, parent_row, parent_id)
            self.data_item_model_controller.data_group = data_group
            # if the new data group matches the one in the image panel, make sure to select the data item too
            image_panel = self.document_controller.selected_image_panel
            if image_panel and data_group == image_panel.data_panel_selection.data_group:
                self.update_data_panel_selection(image_panel.data_panel_selection)
            self.__block1 = saved_block1

        def data_group_widget_key_pressed(index, parent_row, parent_id, key):
            if key.is_delete:
                data_group = self.data_group_model_controller.get_data_group(index, parent_row, parent_id)
                if data_group:
                    container = self.data_group_model_controller.get_data_group_of_parent(parent_row, parent_id)
                    container = container if container else self.document_controller.document_model
                    self.document_controller.remove_data_group_from_container(data_group, container)
            return False

        self.data_group_widget = ui.create_tree_widget(properties={"min-height": 80})
        self.data_group_widget.item_model_controller = self.data_group_model_controller.item_model_controller
        self.data_group_widget.on_current_item_changed = data_group_widget_current_item_changed
        self.data_group_widget.on_item_key_pressed = data_group_widget_key_pressed

        # this message is received when the current item changes in the widget
        self.__block1 = False
        def data_item_widget_current_item_changed(index):
            if not self.__block1:
                data_items = self.data_item_model_controller.get_data_items_flat()
                # check the proper index; there are some cases where it gets out of sync
                data_item = data_items[index] if index >= 0 and index < len(data_items) else None
                # update the selected image panel
                image_panel = self.document_controller.selected_image_panel
                if image_panel:
                    image_panel.data_panel_selection = DataItem.DataItemSpecifier(self.data_item_model_controller.data_group, data_item)

        def data_item_widget_key_pressed(index, key):
            data_item = self.data_item_model_controller.get_data_items_flat()[index] if index >= 0 else None
            if data_item:
                if key.is_delete:
                    container = self.data_item_model_controller.get_data_item_container(self.data_item_model_controller.data_group, data_item)
                    assert data_item in container.data_items
                    container.data_items.remove(data_item)
            return False

        def data_item_double_clicked(index):
            data_item = self.data_item_model_controller.get_data_items_flat()[index] if index >= 0 else None
            if data_item:
                self.document_controller.new_window("data", DataItem.DataItemSpecifier(self.data_item_model_controller.data_group, data_item))

        self.data_item_widget = ui.create_list_widget(properties={"min-height": 240})
        self.data_item_widget.list_model_controller = self.data_item_model_controller.list_model_controller
        self.data_item_widget.on_paint = lambda dc, options: self.data_item_model_controller.paint(dc, options)
        self.data_item_widget.on_current_item_changed = data_item_widget_current_item_changed
        self.data_item_widget.on_item_key_pressed = data_item_widget_key_pressed
        self.data_item_widget.on_item_double_clicked = data_item_double_clicked

        self.splitter = ui.create_splitter_widget("vertical", properties)
        self.splitter.orientation = "vertical"
        self.splitter.add(self.data_group_widget)
        self.splitter.add(self.data_item_widget)
        self.splitter.restore_state("window/v1/data_panel_splitter")

        self.widget = self.splitter

        # connect self as listener. this will result in calls to selected_image_panel_changed
        self.document_controller.add_listener(self)

    def close(self):
        self.splitter.save_state("window/v1/data_panel_splitter")
        self.update_data_panel_selection(DataItem.DataItemSpecifier())
        # close the models
        self.data_item_model_controller.close()
        self.data_group_model_controller.close()
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        super(DataPanel, self).close()

    # if the data_panel_selection gets changed, the data group tree and data item list need
    # to be updated to reflect the new selection. care needs to be taken to not introduce
    # update cycles.
    def update_data_panel_selection(self, data_panel_selection):
        saved_block1 = self.__block1
        self.__block1 = True
        data_group = data_panel_selection.data_group
        data_item = data_panel_selection.data_item
        # first select the right row in the data group widget
        index, parent_row, parent_id = self.data_group_model_controller.get_data_group_index(data_group)
        self.data_group_widget.set_current_row(index, parent_row, parent_id)
        # update the data group that the data item model is tracking
        self.data_item_model_controller.data_group = data_group
        # update the data item selection
        self.data_item_widget.current_index = self.data_item_model_controller.get_data_item_index(data_item)
        self.__block1 = saved_block1

    # this message is received from the document controller when the user or program selects
    # a new image panel by clicking on it or otherwise selecting it.
    # the connection to the document controller is established using add_listener
    def selected_image_panel_changed(self, image_panel):
        data_panel_selection = image_panel.data_panel_selection if image_panel else DataItem.DataItemSpecifier()
        self.update_data_panel_selection(data_panel_selection)

    # this message is received from the document controller when the user or program selects
    # a new data item to be displayed in the current image panel. this can happen when the user
    # selects a new data item in this data panel which will send a message to the current image
    # panel to set the data item, which in turn will result in this message, leading to the selection
    # being updated in this data panel.
    # the connection to the document controller is established using add_listener
    def data_panel_selection_changed_from_image_panel(self, data_panel_selection):
        self.update_data_panel_selection(data_panel_selection)

    # this message comes from the data group model
    def data_group_model_receive_files(self, data_group, index, file_paths):
        if data_group and isinstance(data_group, DataGroup.DataGroup):
            first_data_item = None
            for file_path in file_paths:
                try:
                    raw_image = self.ui.load_rgba_data_from_file(file_path)
                    rgba_image = Image.get_rgb_view(raw_image)
                    if numpy.array_equal(rgba_image[..., 0],rgba_image[..., 1]) and numpy.array_equal(rgba_image[..., 1],rgba_image[..., 2]):
                        image_data = numpy.zeros(raw_image.shape, numpy.uint32)
                        image_data[:, :] = numpy.mean(rgba_image, 2)
                    else:
                        image_data = rgba_image
                    data_item = DataItem.DataItem()
                    data_item.title = os.path.basename(file_path)
                    data_item.master_data = image_data
                    if index >= 0:
                        data_group.data_items.insert(index, data_item)
                    else:
                        data_group.data_items.append(data_item)
                    if not first_data_item:
                        first_data_item = data_item
                except Exception as e:
                    logging.debug("Could not read image %s", file_path)
            if first_data_item:
                # select the first item/group
                image_panel = self.document_controller.selected_image_panel
                if image_panel:
                    image_panel.data_panel_selection = DataItem.DataItemSpecifier(data_group, first_data_item)
                return True
        return False
