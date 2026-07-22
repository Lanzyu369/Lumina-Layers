import type {
  DynamicMaterialLayerCapOption,
  DynamicMaterialRecipe,
  MaterialLayerBenefitPoint,
  MaterialLayerBenefitScope,
} from "../api/types";
import type { ConverterRecipeMaterialDynamic } from "./types";

function emptyDynamicMaterialMetadata(): ConverterRecipeMaterialDynamic {
  return { recipes: [], benefit_curve: [] };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) > 0;
}

function isNonNegativeFiniteNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0;
}

function isRgbTuple(value: unknown): value is [number, number, number] {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every(
      (channel) =>
        isFiniteNumber(channel) && channel >= 0 && channel <= 255,
    )
  );
}

function isRecipeIndexes(value: unknown): value is number[] {
  return Array.isArray(value) && value.every(isNonNegativeInteger);
}

function isLayerCapOption(
  value: unknown,
): value is DynamicMaterialLayerCapOption {
  if (!isRecord(value)) {
    return false;
  }
  const actual = value.actual_recipe_top_to_bottom;
  const printable = value.print_recipe_top_to_bottom;
  return (
    isPositiveInteger(value.max_effective_layer_count) &&
    value.max_effective_layer_count >= 5 &&
    value.max_effective_layer_count <= 10 &&
    isPositiveInteger(value.actual_layer_count) &&
    value.actual_layer_count >= 5 &&
    value.actual_layer_count <= 10 &&
    isRgbTuple(value.matched_srgb) &&
    isRecipeIndexes(actual) &&
    actual.length === value.actual_layer_count &&
    value.actual_layer_count <= value.max_effective_layer_count &&
    isRecipeIndexes(printable) &&
    printable.length >= value.actual_layer_count &&
    actual.every((entry, index) => printable[index] === entry) &&
    printable
      .slice(value.actual_layer_count)
      .every((entry) => entry === printable[value.actual_layer_count]) &&
    isNonNegativeFiniteNumber(value.delta_e00)
  );
}

function isDynamicMaterialRecipe(
  value: unknown,
): value is DynamicMaterialRecipe {
  if (!isRecord(value)) {
    return false;
  }
  const actual = value.actual_recipe_top_to_bottom;
  const printable = value.print_recipe_top_to_bottom;
  const options = value.layer_cap_options;
  if (
    !isRecipeIndexes(actual) ||
    !isRecipeIndexes(printable) ||
    !Array.isArray(options) ||
    !options.every(isLayerCapOption)
  ) {
    return false;
  }
  const caps = options.map((option) => option.max_effective_layer_count);
  const capsAreConsecutive = caps.every(
    (cap, index) => index === 0 || cap === caps[index - 1] + 1,
  );
  const backingValues = [
    ...options.flatMap((option) =>
      option.print_recipe_top_to_bottom.length > option.actual_layer_count
        ? [option.print_recipe_top_to_bottom[option.actual_layer_count]]
        : [],
    ),
    ...(printable.length > (value.actual_layer_count as number)
      ? [printable[value.actual_layer_count as number]]
      : []),
  ];
  return (
    isRgbTuple(value.target_srgb) &&
    isRgbTuple(value.matched_srgb) &&
    isPositiveInteger(value.actual_layer_count) &&
    value.actual_layer_count >= 5 &&
    value.actual_layer_count <= 10 &&
    isNonNegativeInteger(value.padding_layer_count) &&
    actual.length === value.actual_layer_count &&
    printable.length ===
      value.actual_layer_count + value.padding_layer_count &&
    actual.every((entry, index) => printable[index] === entry) &&
    printable
      .slice(value.actual_layer_count)
      .every((entry) => entry === printable[value.actual_layer_count]) &&
    isNonNegativeFiniteNumber(value.selected_delta_e00) &&
    isNonNegativeFiniteNumber(value.best_range_delta_e00) &&
    isNonNegativeFiniteNumber(value.fixed_max_delta_e00) &&
    isNonNegativeFiniteNumber(value.delta_e00_sacrifice) &&
    options.length > 0 &&
    capsAreConsecutive &&
    caps[caps.length - 1] === printable.length &&
    options.every(
      (option) =>
        option.print_recipe_top_to_bottom.length ===
        printable.length,
    ) &&
    backingValues.every((entry) => entry === backingValues[0]) &&
    options.some(
      (option) =>
        option.actual_layer_count === value.actual_layer_count &&
        option.delta_e00 === value.selected_delta_e00 &&
        option.matched_srgb.every(
          (entry, index) => entry === (value.matched_srgb as number[])[index],
        ) &&
        option.actual_recipe_top_to_bottom.every(
          (entry, index) => entry === actual[index],
        ),
    )
  );
}

function isMaterialLayerBenefitPoint(
  value: unknown,
): value is MaterialLayerBenefitPoint {
  if (!isRecord(value)) {
    return false;
  }
  return (
    isPositiveInteger(value.max_effective_layer_count) &&
    isNonNegativeFiniteNumber(value.weighted_mean_delta_e00) &&
    isNonNegativeFiniteNumber(value.marginal_delta_e00_reduction)
  );
}

function isMaterialLayerBenefitScope(
  value: unknown,
): value is MaterialLayerBenefitScope {
  return value === "all_printable_pixels" || value === "automatic_pixels";
}

export function cloneDynamicMaterialRecipe(
  recipe: DynamicMaterialRecipe,
): DynamicMaterialRecipe {
  return {
    ...recipe,
    target_srgb: [...recipe.target_srgb],
    matched_srgb: [...recipe.matched_srgb],
    actual_recipe_top_to_bottom: [...recipe.actual_recipe_top_to_bottom],
    print_recipe_top_to_bottom: [...recipe.print_recipe_top_to_bottom],
    layer_cap_options: recipe.layer_cap_options.map((option) => ({
      ...option,
      matched_srgb: [...option.matched_srgb],
      actual_recipe_top_to_bottom: [
        ...option.actual_recipe_top_to_bottom,
      ],
      print_recipe_top_to_bottom: [...option.print_recipe_top_to_bottom],
    })),
  };
}

export function cloneMaterialLayerBenefitCurve(
  curve: MaterialLayerBenefitPoint[],
): MaterialLayerBenefitPoint[] {
  return curve.map((point) => ({ ...point }));
}

/**
 * Validate and clone imported dynamic results as historical evidence.
 * 校验并深拷贝导入的动态结果，作为历史证据保留。
 *
 * @param value - Untrusted recipe metadata from a share card or sidecar.
 * @param applicable - Whether the imported source is dynamic material mode.
 * @returns Cloned metadata, or empty arrays when invalid or not applicable.
 */
export function restoreImportedDynamicMaterialMetadata(
  value: unknown,
  applicable: boolean,
): ConverterRecipeMaterialDynamic {
  if (
    !applicable ||
    !isRecord(value) ||
    !Array.isArray(value.recipes) ||
    !value.recipes.every(isDynamicMaterialRecipe) ||
    !Array.isArray(value.benefit_curve) ||
    !value.benefit_curve.every(isMaterialLayerBenefitPoint) ||
    value.recipes.some((recipe) => {
      const expectedCaps = value.recipes[0].layer_cap_options.map(
        (option) => option.max_effective_layer_count,
      );
      return (
        recipe.layer_cap_options.length !== expectedCaps.length ||
        recipe.layer_cap_options.some(
          (option, index) =>
            option.max_effective_layer_count !== expectedCaps[index],
        )
      );
    }) ||
    (value.recipes.length > 0 &&
      value.benefit_curve.length !==
        value.recipes[0].layer_cap_options.length) ||
    value.benefit_curve.some(
      (point, index) =>
        point.max_effective_layer_count !==
        value.recipes[0]?.layer_cap_options[index]?.max_effective_layer_count,
    )
) {
    return emptyDynamicMaterialMetadata();
  }
  const rawScope = value.scope;
  if (rawScope !== undefined && !isMaterialLayerBenefitScope(rawScope)) {
    return emptyDynamicMaterialMetadata();
  }
  const rawPixelCount = value.pixel_count;
  if (rawPixelCount !== undefined && !isNonNegativeInteger(rawPixelCount)) {
    return emptyDynamicMaterialMetadata();
  }
  return {
    recipes: value.recipes.map(cloneDynamicMaterialRecipe),
    benefit_curve: cloneMaterialLayerBenefitCurve(value.benefit_curve),
    // Cards written before coverage metadata described the full printable
    // image, so retain that established interpretation on import.
    scope: rawScope ?? "all_printable_pixels",
    pixel_count: rawPixelCount ?? 0,
  };
}
