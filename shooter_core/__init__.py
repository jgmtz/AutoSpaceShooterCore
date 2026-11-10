"""AutoSpaceShooterCore: base reutilizável para bots de shooters verticais (desviar de tiros e abater inimigos)."""
from .config import CoreConfig, PlannerConfig, TrackerConfig, PilotConfig, ShipConfig, LoopConfig, for_screen
from .planner import SpaceTimePlanner, linear_predictor, young_xsv
from .tracking import Tracker
from .pilot import RelativePilot
from .ship import ShipEstimator, ShipState
from .interfaces import GameAdapter, Observation, TouchInput, FrameSource
from .loop import DodgeLoop, AsyncPlanner, FrameContext

__version__ = "0.1.0"
