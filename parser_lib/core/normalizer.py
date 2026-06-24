"""Normalization module - clean and standardize extracted values"""

import re
from typing import Callable, List, Dict, Optional


class BaseNormalizationStep:
    """Abstract normalization step"""

    def apply(self, value: str) -> str:
        """Apply normalization to value
        
        Args:
            value: Input value
            
        Returns:
            Normalized value
        """
        raise NotImplementedError


class StripStep(BaseNormalizationStep):
    """Remove leading/trailing whitespace"""

    def apply(self, value: str) -> str:
        return value.strip()


class RemoveDotsStep(BaseNormalizationStep):
    """Remove all dots"""

    def apply(self, value: str) -> str:
        return value.replace('.', '')


class RemoveTrailingDotStep(BaseNormalizationStep):
    """Remove dots at the end"""

    def apply(self, value: str) -> str:
        return value.rstrip('.')


class RemoveSpacesStep(BaseNormalizationStep):
    """Remove all spaces"""

    def apply(self, value: str) -> str:
        return value.replace(' ', '')


class CollapseSpacesStep(BaseNormalizationStep):
    """Collapse multiple spaces into one"""

    def apply(self, value: str) -> str:
        return re.sub(r'\s+', ' ', value).strip()


class UppercaseStep(BaseNormalizationStep):
    """Convert to uppercase"""

    def apply(self, value: str) -> str:
        return value.upper()


class LowercaseStep(BaseNormalizationStep):
    """Convert to lowercase"""

    def apply(self, value: str) -> str:
        return value.lower()


class DigitsOnlyStep(BaseNormalizationStep):
    """Keep only digits"""

    def apply(self, value: str) -> str:
        return re.sub(r'\D', '', value)


class ReplaceCharStep(BaseNormalizationStep):
    """Replace character or substring"""

    def __init__(self, src: str, dst: str, internal: bool = False):
        self.src = src
        self.dst = dst
        self.internal = internal

    def apply(self, value: str) -> str:
        if self.internal:
            # Replace only between non-whitespace characters
            return re.sub(
                r'(?<=\S)' + re.escape(self.src) + r'(?=\S)',
                self.dst,
                value
            )
        return value.replace(self.src, self.dst)


class ApplyReplacementsStep(BaseNormalizationStep):
    """Apply dictionary of replacements"""

    def __init__(self, replacements: Dict[str, str]):
        self.replacements = replacements

    def apply(self, value: str) -> str:
        for old, new in self.replacements.items():
            value = value.replace(old, new)
        return value


class RegexSubStep(BaseNormalizationStep):
    """Replace using regex pattern"""

    def __init__(self, pattern: str, replacement: str):
        self.pattern = pattern
        self.replacement = replacement

    def apply(self, value: str) -> str:
        return re.sub(self.pattern.strip(), self.replacement.strip(), value)


class ToIntStep(BaseNormalizationStep):
    """Convert to integer"""

    def apply(self, value: str) -> str:
        try:
            return str(int(float(value.replace(',', '.'))))
        except ValueError:
            return value


class ToFloatStep(BaseNormalizationStep):
    """Convert to float with precision"""

    def __init__(self, precision: int = 2):
        self.precision = precision

    def apply(self, value: str) -> str:
        try:
            rounded = round(float(value.replace(',', '.')), self.precision)
            return str(int(rounded)) if self.precision == 0 else str(rounded)
        except ValueError:
            return value


class NormalizerPipeline:
    """Chain of normalization steps"""

    def __init__(self, steps: List[BaseNormalizationStep]):
        self.steps = steps

    def normalize(self, value: str) -> str:
        """Apply all steps sequentially
        
        Args:
            value: Input value
            
        Returns:
            Normalized value
        """
        for step in self.steps:
            value = step.apply(value)
        return value.strip()

    def add_step(self, step: BaseNormalizationStep) -> 'NormalizerPipeline':
        """Add step to pipeline
        
        Args:
            step: Normalization step
            
        Returns:
            Self for chaining
        """
        self.steps.append(step)
        return self


class NormalizerFactory:
    """Factory for creating normalization steps"""

    _steps = {
        'strip': StripStep,
        'remove_dots': RemoveDotsStep,
        'remove_trailing_dot': RemoveTrailingDotStep,
        'remove_spaces': RemoveSpacesStep,
        'collapse_spaces': CollapseSpacesStep,
        'uppercase': UppercaseStep,
        'lowercase': LowercaseStep,
        'digits_only': DigitsOnlyStep,
        'to_int': ToIntStep,
    }

    @classmethod
    def create_step(cls, step_def: str) -> BaseNormalizationStep:
        """Create normalization step from string definition
        
        Args:
            step_def: Step definition (e.g., 'strip', 'to_float:2', 'replace_char:a->b')
            
        Returns:
            Normalization step instance
            
        Raises:
            ValueError: If step is not recognized
        """
        # Handle parametrized steps
        if ':' in step_def:
            name, params = step_def.split(':', 1)
            
            if name == 'replace_char':
                internal = params.startswith('internal:')
                if internal:
                    params = params[len('internal:'):]
                if '->' not in params:
                    raise ValueError(f"Invalid replace_char format: {step_def}")
                src, dst = params.split('->', 1)
                return ReplaceCharStep(src, dst, internal)
            
            elif name == 'to_float':
                try:
                    precision = int(params)
                    return ToFloatStep(precision)
                except ValueError:
                    raise ValueError(f"Invalid to_float precision: {params}")
            
            elif name == 'regex_sub':
                if '->' not in params:
                    raise ValueError(f"Invalid regex_sub format: {step_def}")
                pattern, replacement = params.split('->', 1)
                return RegexSubStep(pattern, replacement)
        
        # Handle simple steps
        if step_def in cls._steps:
            return cls._steps[step_def]()
        
        raise ValueError(f"Unknown normalization step: {step_def}")

    @classmethod
    def create_pipeline(cls, steps_def: List[str], replacements: Optional[Dict[str, str]] = None) -> NormalizerPipeline:
        """Create pipeline from list of step definitions
        
        Args:
            steps_def: List of step definitions
            replacements: Optional replacements dict for apply_replacements
            
        Returns:
            Normalizer pipeline
        """
        steps = []
        for step_def in steps_def:
            if step_def == 'apply_replacements':
                if replacements:
                    steps.append(ApplyReplacementsStep(replacements))
            else:
                steps.append(cls.create_step(step_def))
        return NormalizerPipeline(steps)

    @classmethod
    def register_step(cls, name: str, step_class: type):
        """Register custom normalization step
        
        Args:
            name: Step name
            step_class: Step class (must inherit BaseNormalizationStep)
        """
        if not issubclass(step_class, BaseNormalizationStep):
            raise TypeError(f"{step_class} must inherit BaseNormalizationStep")
        cls._steps[name] = step_class
