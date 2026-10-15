from .baikal import BaikalCarrier
from .base import BaseCarrier
from .cdek import CdekCarrier
from .dellin import DellinCarrier
from .dpd import DpdCarrier
from .kit import KitCarrier
from .manual import BuroCarrier, MagistralCarrier
from .pecom import PecomCarrier
from .rts import RtsCarrier

CARRIERS: list[BaseCarrier] = [
    DellinCarrier(),
    RtsCarrier(),
    DpdCarrier(),
    CdekCarrier(),
    PecomCarrier(),
    BaikalCarrier(),
    MagistralCarrier(),
    BuroCarrier(),
    KitCarrier(),
]
