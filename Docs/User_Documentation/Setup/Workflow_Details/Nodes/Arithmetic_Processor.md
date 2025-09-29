### **Data Manipulation: The Arithmetic Processor Node**

The **`ArithmeticProcessor`** node is a simple utility for performing basic mathematical calculations within a workflow.
Its purpose is to take an expression containing two numbers and one operator, resolve any workflow variables, compute
the result, and make it available to subsequent nodes. This is useful for tasks like incrementing counters, calculating
costs, or performing any simple arithmetic based on the outputs of other nodes.

-----

#### **How It Works**

A `ArithmeticProcessor` node's execution is straightforward:

1. **Configuration Loading:** The processor loads the node's JSON configuration, primarily the `expression` string.
2. **Variable Substitution:** The `expression` field is processed by the `WorkflowVariableManager`. All placeholders (
   e.g., `{agent1Output}`, `{my_custom_variable}`) are replaced with their current values from the `ExecutionContext`.
3. **Expression Parsing:** The system parses the resolved string, expecting a simple format of
   `number operator number` (e.g., `10 + 5`). Supported operators are addition (`+`), subtraction (`-`),
   multiplication (`*`), and division (`/`).
4. **Calculation:** The arithmetic operation is performed.
5. **Output Handling:** The node returns the result of the calculation as a string.
    * If the expression is malformed, contains non-numeric values after substitution, or results in an error (like
      division by zero), the node returns the string `"-1"`.
    * The output is captured internally as a variable (e.g., `{agent1Output}`, `{agent2Output}`, etc.), making it
      available for use by subsequent nodes in the workflow.

-----

#### **Properties**

| Property           | Type    | Required | Default | Description                                                                                                               |
|:-------------------|:--------|:---------|:--------|:--------------------------------------------------------------------------------------------------------------------------|
| **`type`**         | String  | Yes      | N/A     | Must be `"ArithmeticProcessor"`.                                                                                          |
| **`title`**        | String  | No       | `""`    | A descriptive name for the node, used for logging and debugging.                                                          |
| **`expression`**   | String  | Yes      | N/A     | The mathematical expression to evaluate. It must consist of two numbers and one operator (e.g., `{agent1Output} * 1.07`). |
| **`returnToUser`** | Boolean | No       | `false` | It is highly unlikely this would be set to `true`, as the node is designed for internal data processing.                  |

-----

#### **Variable Usage**

The `expression` property supports all available workflow variables, including custom top-level variables, agent
outputs (`{agent1Output}`), and date/time variables. The variables are expected to resolve to numeric values for the
calculation to succeed.

-----

#### **Full Syntax Example**

This example shows a node that takes the output from a previous node (`agent1Output`), which is assumed to be a
subtotal, and calculates the final price by adding a 7% tax.

```json
{
  "title": "Calculate Final Price with Tax",
  "type": "ArithmeticProcessor",
  "expression": "{agent1Output} * 1.07",
  "returnToUser": false
}
```