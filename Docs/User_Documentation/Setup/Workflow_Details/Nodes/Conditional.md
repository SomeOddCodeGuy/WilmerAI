### **Developer Guide: The Conditional Node**

Here is the updated documentation for the new `Conditional` node.

### **Logic & Control Flow: The Conditional Node**

The **`Conditional`** node is a powerful control flow utility that evaluates a complex logical expression. Its purpose
is to return the string `"TRUE"` or `"FALSE"` based on the outcome. This node is a fundamental building block for
creating dynamic workflows, as its output can be used by a `ConditionalCustomWorkflow` node to decide whether or not to
execute a subsequent sub-workflow.

It supports:

* Comparisons between **numbers or strings** (e.g., `{score} > 90`, `'{status}' == 'complete'`).
* Logical operators **`AND`** and **`OR`** to combine multiple conditions.
* **Parentheses `()`** to group expressions and control the order of evaluation.

-----

#### **How It Works**

1. **Configuration Loading:** The processor loads the node's JSON configuration and its `condition` string.
2. **Variable Substitution:** The `condition` field is processed, replacing any placeholders like `{agent1Output}` with
   their runtime values.
3. **Expression Parsing:** The system uses a standard Shunting-yard algorithm to parse the entire expression. This
   correctly handles operator precedence (**`AND`** is evaluated before **`OR`**) and nested expressions within
   parentheses.
4. **Type Inference:** During evaluation, the node intelligently parses each value.
    * A value enclosed in single or double quotes (e.g., `"Admin"`) is treated as a **string**.
    * The special words `TRUE` and `FALSE` (case-insensitive, **without quotes**) are treated as **booleans**.
    * Any other unquoted value is first attempted as a **number**. If it's not a valid number, it's treated as a *
      *string** (e.g., the resolved output of a variable).
5. **Evaluation:** The full expression is evaluated according to logical rules. Comparing a number to a string (e.g.,
   `5 > "cat"`) will safely result in `FALSE`.
6. **Output Handling:**
    * The node returns the string `"TRUE"` if the final expression evaluates to true, and `"FALSE"` otherwise.
    * If the condition is malformed or a syntax error occurs, it safely returns `"FALSE"` and logs a warning.
    * The string output is captured as a variable (e.g., `{agent2Output}`), which can be directly used to control other
      nodes.

-----

#### **Properties**

| Property           | Type    | Required | Default | Description                                                                                                     |
|:-------------------|:--------|:---------|:--------|:----------------------------------------------------------------------------------------------------------------|
| **`type`**         | String  | Yes      | N/A     | Must be `"Conditional"`.                                                                                        |
| **`title`**        | String  | No       | `""`    | A descriptive name for the node, used for logging and debugging.                                                |
| **`condition`**    | String  | Yes      | N/A     | The logical expression to evaluate (e.g., `({val} >= 100 AND '{status}' != 'ERROR') OR {is_override} == TRUE`). |
| **`returnToUser`** | Boolean | No       | `false` | This node is designed for internal logic and its output is not intended for the end-user.                       |

-----

#### **Variable Usage**

The `condition` property supports all available workflow variables. The node will automatically determine the type (
number, string, or boolean) of the resolved variable. For string literals in the condition itself, **it is best practice
to enclose them in quotes** (e.g., `"completed"`).

-----

#### **⚠️ Critical Usage Note: Comparing Booleans vs. Strings**

The node's type inference engine makes a critical distinction between a boolean `TRUE` and a string `'TRUE'`. **This is
especially important when checking the output of a previous `Conditional` node.**

The `Conditional` node outputs the raw string `TRUE` or `FALSE`. When this output (e.g., `{agent3Output}`) is used in
another condition, the parser interprets it as a **boolean**.

* **INCORRECT Comparison:** `"{agent3Output} == 'TRUE'"`

    * This will evaluate as `(boolean) True == (string) 'TRUE'`, which is **FALSE**.

* **CORRECT Comparison:** `"{agent3Output} == TRUE"`

    * This will evaluate as `(boolean) True == (boolean) True`, which is **TRUE**.

Always compare the output of a `Conditional` node against the unquoted keywords `TRUE` or `FALSE`.

-----

#### **Full Syntax Examples**

**Simple Numeric Comparison**
This example checks if a calculated score from a previous node is passing.

```json
{
  "title": "Check if score is passing",
  "type": "Conditional",
  "condition": "{agent4Output} >= 65"
}
```

**Combined Logic with `AND`**
This example checks if the string output from a task is `'complete'` and was not assigned to a user named `'guest'`.

```json
{
  "title": "Check if task is complete and not a guest task",
  "type": "Conditional",
  "condition": "{agent2Output} == 'complete' AND {agent1Output} != 'guest'"
}
```

**Complex Logic with `OR` and Parentheses**
This example demonstrates how to check for multiple valid states or an override condition. The parentheses ensure the
`OR` conditions are evaluated together before the `AND`. Note the correct comparison to the unquoted boolean `TRUE`.

```json
{
  "title": "Check for valid state or admin override",
  "type": "Conditional",
  "condition": "({agent1Output} == 'Admin') OR ({agent2Output} == 'Approved' AND {agent3Output} == TRUE)"
}
```