import pandas as pd
import numpy as np
import FeatCreation

# Test case 1: df[independent] > 0
df = pd.DataFrame({'A': [1, 2, 3]})
independent = 'A'
expected_output = pd.DataFrame({'A': [1, 2, 3], 'A_zeroOrValue': [1, 1, 1]})
output = FeatCreation.zeroOrValue(df, independent)
print(output)
assert output.equals(expected_output), "Test case 1 failed"

# Test case 2: df[independent] <= 0
df = pd.DataFrame({'B': [-1, 0, 1]})
independent = 'B'
expected_output = pd.DataFrame({'B': [-1, 0, 1], 'B_zeroOrValue': [0, 0, 1]})
output = FeatCreation.zeroOrValue(df, independent)
print(output)
assert output.equals(expected_output), "Test case 2 failed"

# Test case 3: df contains nulls
df = pd.DataFrame({'C': [1, 2, None]})
independent = 'C'
expected_output = pd.DataFrame({'C': [1, 2, None], 'C_zeroOrValue': [1, 1, None]})
output = FeatCreation.zeroOrValue(df, independent)
print(output)
assert output.equals(expected_output), "Test case 3 failed"

# Additional test cases can be added here

print("All test cases passed")