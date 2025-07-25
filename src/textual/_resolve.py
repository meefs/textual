from __future__ import annotations

from fractions import Fraction
from itertools import accumulate
from typing import TYPE_CHECKING, Iterable, Sequence, cast

from typing_extensions import Literal

from textual.box_model import BoxModel
from textual.css.scalar import Scalar
from textual.css.styles import RenderStyles
from textual.geometry import Size

if TYPE_CHECKING:
    from textual.widget import Widget


def resolve(
    dimensions: Sequence[Scalar],
    total: int,
    gutter: int,
    size: Size,
    viewport: Size,
    *,
    expand: bool = False,
    shrink: bool = False,
    minimums: list[int] | None = None,
) -> list[tuple[int, int]]:
    """Resolve a list of dimensions.

    Args:
        dimensions: Scalars for column / row sizes.
        total: Total space to divide.
        gutter: Gutter between rows / columns.
        size: Size of container.
        viewport: Size of viewport.

    Returns:
        List of (<OFFSET>, <LENGTH>)
    """
    resolved: list[tuple[Scalar, Fraction | None]] = [
        (
            (scalar, None)
            if scalar.is_fraction
            else (scalar, scalar.resolve(size, viewport))
        )
        for scalar in dimensions
    ]

    from_float = Fraction.from_float
    total_fraction = from_float(
        sum([scalar.value for scalar, fraction in resolved if fraction is None])
    )

    total_gutter = gutter * (len(dimensions) - 1)
    if total_fraction:
        consumed = sum([fraction for _, fraction in resolved if fraction is not None])
        remaining = max(Fraction(0), Fraction(total - total_gutter) - consumed)
        fraction_unit = Fraction(remaining, total_fraction)
        resolved_fractions = [
            from_float(scalar.value) * fraction_unit if fraction is None else fraction
            for scalar, fraction in resolved
        ]
    else:
        resolved_fractions = cast(
            "list[Fraction]", [fraction for _, fraction in resolved]
        )

    fraction_gutter = Fraction(gutter)

    if expand or shrink:
        total_space = total - total_gutter
        used_space = sum(resolved_fractions)
        if expand:
            remaining_space = total_space - used_space
            if remaining_space > 0:
                resolved_fractions = [
                    width + Fraction(width, used_space) * remaining_space
                    for width in resolved_fractions
                ]
        if shrink:
            one = Fraction(1)
            excess_space = used_space - total_space
            if minimums is not None and excess_space > 0:
                for index, (minimum_width, width) in enumerate(
                    zip(map(Fraction, minimums), resolved_fractions)
                ):
                    remove_space = max(Fraction(width, used_space), one) * excess_space
                    updated_width = max(minimum_width, width - remove_space)
                    resolved_fractions[index] = updated_width
                    used_space = used_space - width + updated_width
                    excess_space = used_space - total_space
                    if excess_space <= 0:
                        break

                used_space = sum(resolved_fractions)
                excess_space = used_space - total_space

            if excess_space > 0:
                resolved_fractions = [
                    width - Fraction(width, used_space) * excess_space
                    for width in resolved_fractions
                ]

    offsets = [0] + [
        fraction.__floor__()
        for fraction in accumulate(
            value
            for fraction in resolved_fractions
            for value in (fraction, fraction_gutter)
        )
    ]
    results = [
        (offset1, offset2 - offset1)
        for offset1, offset2 in zip(offsets[::2], offsets[1::2])
    ]

    return results


def resolve_fraction_unit(
    widget_styles: Iterable[RenderStyles],
    size: Size,
    viewport_size: Size,
    remaining_space: Fraction,
    resolve_dimension: Literal["width", "height"] = "width",
) -> Fraction:
    """Calculate the fraction.

    Args:
        widget_styles: Styles for widgets with fraction units.
        size: Container size.
        viewport_size: Viewport size.
        remaining_space: Remaining space for fr units.
        resolve_dimension: Which dimension to resolve.

    Returns:
        The value of 1fr.
    """
    _Fraction = Fraction
    if not remaining_space or not widget_styles:
        return _Fraction(1)

    initial_space = remaining_space

    def resolve_scalar(
        scalar: Scalar | None, fraction_unit: Fraction = Fraction(1)
    ) -> Fraction | None:
        """Resolve a scalar if it is not None.

        Args:
            scalar: Optional scalar to resolve.
            fraction_unit: Size of 1fr.

        Returns:
            Fraction if resolved, otherwise None.
        """
        return (
            None
            if scalar is None
            else scalar.resolve(size, viewport_size, fraction_unit)
        )

    resolve: list[tuple[Scalar, Fraction | None, Fraction | None]] = []

    if resolve_dimension == "width":
        resolve = [
            (
                cast(Scalar, styles.width),
                resolve_scalar(styles.min_width),
                resolve_scalar(styles.max_width),
            )
            for styles in widget_styles
            if styles.overlay != "screen"
        ]
    else:
        resolve = [
            (
                cast(Scalar, styles.height),
                resolve_scalar(styles.min_height),
                resolve_scalar(styles.max_height),
            )
            for styles in widget_styles
            if styles.overlay != "screen"
        ]

    resolved: list[Fraction | None] = [None] * len(resolve)
    remaining_fraction = Fraction(sum(scalar.value for scalar, _, _ in resolve))

    while remaining_fraction > 0:
        remaining_space_changed = False
        resolve_fraction = _Fraction(remaining_space, remaining_fraction)
        for index, (scalar, min_value, max_value) in enumerate(resolve):
            value = resolved[index]
            if value is None:
                resolved_scalar = scalar.resolve(size, viewport_size, resolve_fraction)
                if min_value is not None and resolved_scalar < min_value:
                    remaining_space -= min_value
                    remaining_fraction -= _Fraction(scalar.value)
                    resolved[index] = min_value
                    remaining_space_changed = True
                elif max_value is not None and resolved_scalar > max_value:
                    remaining_space -= max_value
                    remaining_fraction -= _Fraction(scalar.value)
                    resolved[index] = max_value
                    remaining_space_changed = True

        if not remaining_space_changed:
            break

    return (
        Fraction(remaining_space, remaining_fraction)
        if remaining_fraction > 0
        else initial_space
    )


def resolve_box_models(
    dimensions: list[Scalar | None],
    widgets: list[Widget],
    size: Size,
    viewport_size: Size,
    margin: Size,
    resolve_dimension: Literal["width", "height"] = "width",
    greedy: bool = True,
) -> list[BoxModel]:
    """Resolve box models for a list of dimensions

    Args:
        dimensions: A list of Scalars or Nones for each dimension.
        widgets: Widgets in resolve.
        size: Size of container.
        viewport_size: Viewport size.
        margin: Total space occupied by margin
        resolve_dimension: Which dimension to resolve.

    Returns:
        List of resolved box models.
    """

    margin_width, margin_height = margin
    fraction_width = Fraction(size.width)
    fraction_height = Fraction(size.height)
    fraction_zero = Fraction(0)
    margin_size = size - margin

    margins = [widget.styles.margin.totals for widget in widgets]

    # Fixed box models
    box_models: list[BoxModel | None] = [
        (
            None
            if _dimension is not None and _dimension.is_fraction
            else widget._get_box_model(
                size,
                viewport_size,
                (
                    fraction_zero
                    if (_width := fraction_width - margin_width) < 0
                    else _width
                ),
                (
                    fraction_zero
                    if (_height := fraction_height - margin_height) < 0
                    else _height
                ),
                greedy=greedy,
            )
        )
        for (_dimension, widget, (margin_width, margin_height)) in zip(
            dimensions, widgets, margins
        )
    ]

    if None not in box_models:
        # No fr units, so we're done
        return cast("list[BoxModel]", box_models)

    # If all box models have been calculated
    widget_styles = [widget.styles for widget in widgets]
    if resolve_dimension == "width":
        total_remaining = int(
            sum(
                [
                    box_model.width
                    for widget, box_model in zip(widgets, box_models)
                    if (box_model is not None and widget.styles.overlay != "screen")
                ]
            )
        )

        remaining_space = int(max(0, size.width - total_remaining - margin_width))
        fraction_unit = resolve_fraction_unit(
            [
                styles
                for styles in widget_styles
                if styles.width is not None
                and styles.width.is_fraction
                and styles.overlay != "screen"
            ],
            size,
            viewport_size,
            Fraction(remaining_space),
            resolve_dimension,
        )
        width_fraction = fraction_unit
        height_fraction = Fraction(margin_size.height)
    else:
        total_remaining = int(
            sum(
                [
                    box_model.height
                    for widget, box_model in zip(widgets, box_models)
                    if (box_model is not None and widget.styles.overlay != "screen")
                ]
            )
        )

        remaining_space = int(max(0, size.height - total_remaining - margin_height))
        fraction_unit = resolve_fraction_unit(
            [
                styles
                for styles in widget_styles
                if styles.height is not None
                and styles.height.is_fraction
                and styles.overlay != "screen"
            ],
            size,
            viewport_size,
            Fraction(remaining_space),
            resolve_dimension,
        )
        width_fraction = Fraction(margin_size.width)
        height_fraction = fraction_unit

    box_models = [
        box_model
        or widget._get_box_model(
            size, viewport_size, width_fraction, height_fraction, greedy=greedy
        )
        for widget, box_model in zip(widgets, box_models)
    ]

    return cast("list[BoxModel]", box_models)
