"""
    Contains classes related to regions of data items.
"""

# futures
from __future__ import absolute_import

# standard libraries
# None

# third party libraries
# None

# local libraries
from nion.swift.model import Graphics
from nion.ui import Binding
from nion.ui import Observable


class Region(Observable.Observable, Observable.Broadcaster, Observable.ManagedObject):
    # Regions are associated with exactly one data item.

    def __init__(self, type):
        super(Region, self).__init__()
        self.define_type(type)
        self.define_property("label", changed=self._property_changed, validate=lambda s: str(s))
        # TODO: add unit type to region (relative, absolute, calibrated)

    def about_to_be_removed(self):
        pass

    def _property_changed(self, name, value):
        self.notify_set_property(name, value)

    @property
    def graphic(self):
        return None

    def remove_region_graphic(self, region_graphic):
        # message from the graphic when its being removed
        self.notify_listeners("remove_region_because_graphic_removed", self)  # goes to operation


class PointRegion(Region):

    def __init__(self):
        super(PointRegion, self).__init__("point-region")
        self.define_property("position", (0.5, 0.5), changed=self._property_changed, validate=lambda s: tuple(s))
        self.__graphic = Graphics.PointGraphic()
        self.__graphic.set_region(self)
        self.__graphic.color = "#F80"
        self.__graphic.add_listener(self)
        self.__position_binding = RegionPropertyToGraphicBinding(self, "position", self.__graphic, "position")
        self.__label_binding = RegionPropertyToGraphicBinding(self, "label", self.__graphic, "label")

    @property
    def graphic(self):
        return self.__graphic


class LineRegion(Region):

    def __init__(self):
        super(LineRegion, self).__init__("line-region")
        def read_vector(managed_property, properties):
            # read the vector defined by managed_property from the properties dict.
            start = properties.get("start", (0.0, 0.0))
            end = properties.get("end", (1.0, 1.0))
            return start, end
        def write_vector(managed_property, properties, value):
            # write the vector (value) defined by managed_property to the properties dict.
            properties["start"] = value[0]
            properties["end"] = value[1]
        # vector is stored in image normalized coordinates
        self.define_property("vector", ((0.0, 0.0), (1.0, 1.0)), changed=self.__vector_changed, reader=read_vector, writer=write_vector, validate=lambda s: (tuple(s[0]), tuple(s[1])))
        self.define_property("width", 1.0, changed=self._property_changed, validate=lambda s: float(s))
        self.__graphic = Graphics.LineProfileGraphic()
        self.__graphic.set_region(self)
        self.__graphic.color = "#F80"
        self.__graphic.end_arrow_enabled = True
        self.__graphic.add_listener(self)
        self.__vector_binding = RegionPropertyToGraphicBinding(self, "vector", self.__graphic, "vector")
        self.__width_binding = RegionPropertyToGraphicBinding(self, "width", self.__graphic, "width")
        self.__label_binding = RegionPropertyToGraphicBinding(self, "label", self.__graphic, "label")

    def __vector_changed(self, name, value):
        self._property_changed(name, value)
        self.notify_set_property("start", value[0])
        self.notify_set_property("end", value[1])

    def __get_start(self):
        return self.vector[0]
    def __set_start(self, start):
        self.vector = start, self.end
    start = property(__get_start, __set_start)

    def __get_end(self):
        return self.vector[1]
    def __set_end(self, end):
        self.vector = self.start, end
    end = property(__get_end, __set_end)

    @property
    def graphic(self):
        return self.__graphic


class RectRegion(Region):

    def __init__(self):
        super(RectRegion, self).__init__("rectangle-region")
        self.define_property("center", (0.0, 0.0), changed=self._property_changed, validate=lambda s: tuple(s))
        self.define_property("size", (1.0, 1.0), changed=self._property_changed, validate=lambda s: tuple(s))
        # TODO: add rotation property to rect region
        self.__graphic = Graphics.RectangleGraphic()
        self.__graphic.set_region(self)
        self.__graphic.color = "#F80"
        self.__graphic.add_listener(self)
        self.__center_binding = RegionPropertyToGraphicBinding(self, "center", self.__graphic, "center")
        self.__size_binding = RegionPropertyToGraphicBinding(self, "size", self.__graphic, "size")
        self.__label_binding = RegionPropertyToGraphicBinding(self, "label", self.__graphic, "label")

    @property
    def graphic(self):
        return self.__graphic

    def __get_bounds(self):
        center = self.center
        size = self.size
        return (center[0] - size[0] * 0.5, center[1] - size[1] * 0.5), size
    def __set_bounds(self, bounds):
        self.center = bounds[0][0] + bounds[1][0] * 0.5, bounds[0][1] + bounds[1][1] * 0.5
        self.size = bounds[1]
    bounds = property(__get_bounds, __set_bounds)

    def _property_changed(self, name, value):
        # override to implement dependency. argh.
        self.notify_set_property(name, value)
        self.notify_set_property("bounds", self.bounds)


class EllipseRegion(Region):

    def __init__(self):
        super(EllipseRegion, self).__init__("ellipse-region")
        self.define_property("center", (0.0, 0.0), changed=self._property_changed, validate=lambda s: tuple(s))
        self.define_property("size", (1.0, 1.0), changed=self._property_changed, validate=lambda s: tuple(s))
        self.define_property("angle", 0.0, changed=self._property_changed, validate=lambda s: float(s))
        self.__graphic = Graphics.EllipseGraphic()
        self.__graphic.set_region(self)
        self.__graphic.color = "#F80"
        self.__graphic.add_listener(self)
        self.__center_binding = RegionPropertyToGraphicBinding(self, "center", self.__graphic, "center")
        self.__size_binding = RegionPropertyToGraphicBinding(self, "size", self.__graphic, "size")
        self.__label_binding = RegionPropertyToGraphicBinding(self, "label", self.__graphic, "label")

    @property
    def graphic(self):
        return self.__graphic

    def __get_bounds(self):
        center = self.center
        size = self.size
        return (center[0] - size[0] * 0.5, center[1] - size[1] * 0.5), size
    def __set_bounds(self, bounds):
        self.center = bounds[0][0] + bounds[1][0] * 0.5, bounds[0][1] + bounds[1][1] * 0.5
        self.size = bounds[1]
    bounds = property(__get_bounds, __set_bounds)

    def _property_changed(self, name, value):
        # override to implement dependency. argh.
        self.notify_set_property(name, value)
        self.notify_set_property("bounds", self.bounds)


class IntervalRegion(Region):

    def __init__(self):
        super(IntervalRegion, self).__init__("interval-region")
        def read_interval(managed_property, properties):
            # read the interval defined by managed_property from the properties dict.
            start = properties.get("start", 0.0)
            end = properties.get("end", 1.0)
            return start, end
        def write_interval(managed_property, properties, value):
            # write the interval (value) defined by managed_property to the properties dict.
            properties["start"] = value[0]
            properties["end"] = value[1]
        self.define_property("interval", (0.0, 1.0), changed=self.__interval_changed, reader=read_interval, writer=write_interval, validate=lambda s: tuple(s))
        self.__graphic = Graphics.IntervalGraphic()
        self.__graphic.set_region(self)
        self.__graphic.color = "#F80"
        self.__graphic.add_listener(self)
        self.__interval_binding = RegionPropertyToGraphicBinding(self, "interval", self.__graphic, "interval")
        self.__label_binding = RegionPropertyToGraphicBinding(self, "label", self.__graphic, "label")

    @property
    def graphic(self):
        return self.__graphic

    def __interval_changed(self, name, value):
        self._property_changed(name, value)
        self.notify_set_property("start", value[0])
        self.notify_set_property("end", value[1])

    def __get_start(self):
        return self.interval[0]
    def __set_start(self, start):
        self.interval = start, self.end
    start = property(__get_start, __set_start)

    def __get_end(self):
        return self.interval[1]
    def __set_end(self, end):
        self.interval = self.start, end
    end = property(__get_end, __set_end)




class RegionPropertyToGraphicBinding(Binding.PropertyBinding):

    """
        Binds a property of an operation item to a property of a graphic item.
    """

    def __init__(self, region, region_property_name, graphic, graphic_property_name):
        super(RegionPropertyToGraphicBinding, self).__init__(region, region_property_name)
        self.__graphic = graphic
        self.__graphic.add_observer(self)
        self.__graphic_property_name = graphic_property_name
        self.__region_property_name = region_property_name
        self.target_setter = lambda value: setattr(self.__graphic, graphic_property_name, value)

    def close(self):
        self.__graphic.remove_observer(self)
        self.__graphic = None
        super(RegionPropertyToGraphicBinding, self).close()

    # watch for property changes on the graphic.
    def property_changed(self, sender, property_name, property_value):
        super(RegionPropertyToGraphicBinding, self).property_changed(sender, property_name, property_value)
        if sender == self.__graphic and property_name == self.__graphic_property_name:
            old_property_value = getattr(self.source, self.__region_property_name)
            # to prevent message loops, check to make sure it changed
            if property_value != old_property_value:
                self.update_source(property_value)


def region_factory(lookup_id):
    build_map = {
        "point-region": PointRegion,
        "line-region": LineRegion,
        "rectangle-region": RectRegion,
        "ellipse-region": EllipseRegion,
        "interval-region": IntervalRegion,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None
