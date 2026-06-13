from typing import Annotated

from fastapi import Query


class PaginationParams:
    def __init__(
        self,
        page_size: Annotated[
            int,
            Query(
                ge=1,
                le=100,
                description='Количество элементов на странице',
                example=50,
            ),
        ] = 50,
        page_number: Annotated[
            int,
            Query(
                ge=1,
                description='Номер страницы',
                example=1,
            ),
        ] = 1,
    ) -> None:
        self.page_size = page_size
        self.page_number = page_number
