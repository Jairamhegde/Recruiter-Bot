"""Maximum-weight one-to-one assignment, by the Hungarian algorithm (D-52).

The problem: rows are the skills a job requires, columns are the skills a candidate has, and
weights[row][column] says how much credit that candidate skill earns for that requirement
(0 for none). Each candidate skill may cover at most one requirement, and each requirement
takes at most one candidate skill. Which pairing earns the most credit in total?

Trying every combination takes exponentially longer as the lists grow: 5 seconds at 8
requirements, 109 seconds at 10. The Hungarian algorithm finds the same best answer in time
proportional to rows x rows x columns, a few milliseconds for 20 requirements.
"""


def best_assignment(weights: list[list[int]]) -> list[int | None]:
    """For each row, the column it is paired with, or None if it earns nothing.

    Weights are whole numbers, so ties are exact. Rows with no positive weight stay unpaired.
    """
    rows = len(weights)
    if rows == 0:
        return []
    real_columns = len(weights[0])

    # One spare column per row, with weight 0: a row paired with a spare column is simply unpaired.
    # This keeps the problem "every row gets a column" even when there are fewer useful columns than rows.
    columns = real_columns + rows

    # The algorithm below finds the cheapest pairing, so negate the weights to find the richest.
    cost = [[-weight for weight in row] + [0] * rows for row in weights]

    paired_column = _cheapest_pairing(cost, rows, columns)

    result: list[int | None] = []
    for row in range(rows):
        column = paired_column[row]
        if column < real_columns and weights[row][column] > 0:
            result.append(column)
        else:
            result.append(None)
    return result


def _cheapest_pairing(cost: list[list[int]], rows: int, columns: int) -> list[int]:
    """Gives every row its own column at the lowest total cost. Needs columns >= rows.

    The Hungarian algorithm in its shortest-augmenting-path form. Each row is added in turn;
    "potentials" (row_bonus, column_bonus) adjust the costs so that the cheapest unpaired
    column can always be found, and the pairing is improved along the cheapest path.
    Indices here start at 1; index 0 is a helper slot.
    """
    infinity = float("inf")
    row_bonus = [0] * (rows + 1)
    column_bonus = [0] * (columns + 1)
    row_of_column = [0] * (columns + 1)   # which row currently holds each column (0 = nobody)
    previous_column = [0] * (columns + 1)  # the path back, for improving the pairing

    for new_row in range(1, rows + 1):
        row_of_column[0] = new_row
        current_column = 0
        cheapest_reach = [infinity] * (columns + 1)
        visited = [False] * (columns + 1)

        # Grow a search from the new row until it reaches a column nobody holds.
        while True:
            visited[current_column] = True
            row = row_of_column[current_column]
            step = infinity
            next_column = 0
            for column in range(1, columns + 1):
                if visited[column]:
                    continue
                reach = cost[row - 1][column - 1] - row_bonus[row] - column_bonus[column]
                if reach < cheapest_reach[column]:
                    cheapest_reach[column] = reach
                    previous_column[column] = current_column
                if cheapest_reach[column] < step:
                    step = cheapest_reach[column]
                    next_column = column
            for column in range(columns + 1):
                if visited[column]:
                    row_bonus[row_of_column[column]] += step
                    column_bonus[column] -= step
                else:
                    cheapest_reach[column] -= step
            current_column = next_column
            if row_of_column[current_column] == 0:
                break

        # Walk the path back, handing each column on the path to the row before it.
        while current_column != 0:
            earlier_column = previous_column[current_column]
            row_of_column[current_column] = row_of_column[earlier_column]
            current_column = earlier_column

    paired_column = [0] * rows
    for column in range(1, columns + 1):
        if row_of_column[column] != 0:
            paired_column[row_of_column[column] - 1] = column - 1
    return paired_column
