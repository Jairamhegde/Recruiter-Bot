"""Maximum-weight one-to-one assignment, by the Hungarian algorithm."""


def best_assignment(weights: list[list[int]]) -> list[int | None]:
    """For each row, its paired column, or None if it earns nothing."""
    rows = len(weights)
    if rows == 0:
        return []
    real_columns = len(weights[0])

    # A zero-weight spare column per row, so a row can stay unpaired.
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
    """Gives every row its own column at the lowest total cost (shortest augmenting path)."""
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
