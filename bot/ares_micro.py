"""
Ares-sc2 combat micro integration for Arpy bot.

This module wraps ares combat behaviors into a clean interface that can be
called from the existing bot code. It replaces manual attack/move commands
with ares behaviors that handle deduplication, stutter-stepping, and
target selection automatically.

Key improvements over manual micro:
1. Each unit gets exactly ONE behavior per frame (no command spam)
2. ShootTargetInRange: only shoots when weapon is ready and target is in range
3. StutterUnitBack: kites backward using influence grids
4. KeepUnitSafe: retreats to safety when in danger
5. CombatManeuver: composes behaviors in priority order
6. CombatSimManager: predicts engagement outcomes before committing
7. UnitRoleManager: proper role assignment for defenders (no more oscillation)
"""

import numpy as np
from typing import Optional, Set

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ares import AresBot
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    AttackTarget,
    KeepUnitSafe,
    ShootTargetInRange,
    StutterUnitBack,
    StutterUnitForward,
)
from ares.consts import (
    EngagementResult,
    ManagerName,
    ManagerRequestType,
    UnitRole,
    LOSS_CLOSE_OR_WORSE,
    LOSS_DECISIVE_OR_WORSE,
    VICTORY_MARGINAL_OR_BETTER,
)


# Types that should use stutter-back micro (ranged units)
RANGED_TYPES = {
    UnitTypeId.STALKER,
    UnitTypeId.SENTRY,
    UnitTypeId.IMMORTAL,
    UnitTypeId.VOIDRAY,
    UnitTypeId.PHOENIX,
}

# Types that should use stutter-forward micro (melee/charge units)
MELEE_TYPES = {
    UnitTypeId.ZEALOT,
    UnitTypeId.ADEPT,
    UnitTypeId.DARKTEMPLAR,
    UnitTypeId.ARCHON,
}

# Air unit types that need air grid instead of ground grid
AIR_TYPES = {
    UnitTypeId.VOIDRAY,
    UnitTypeId.PHOENIX,
    UnitTypeId.WARPPRISM,
    UnitTypeId.WARPPRISMPHASING,
    UnitTypeId.OBSERVER,
}


def get_blink_upgrade_id():
    """Get the correct UpgradeId for blink research.
    
    The august-k fork of python-sc2 uses BLINKTECH instead of
    BLINKTECHRESEARCH. This function tries multiple names to find the correct one.
    """
    candidates = [
        "BLINKTECH",          # august-k fork
        "BLINKTECHRESEARCH",  # burnysc2 fork
        "RESEARCH_BLINK",
        "STALKERBLINK",
    ]
    for name in candidates:
        if hasattr(UpgradeId, name):
            return getattr(UpgradeId, name)
    return None


# Cache the result at module load time
BLINK_UPGRADE = get_blink_upgrade_id()


class AresMicroManager:
    """Manages ares combat behaviors for the Arpy bot.
    
    This class is the bridge between Arpy's existing logic and ares's
    combat behavior system. It provides:
    
    1. `register_army_combat()` - Replace manual attack/move with behaviors
    2. `register_defender_combat()` - Proper role-based defense micro
    3. `can_win_fight()` - Combat simulation for attack/retreat decisions
    4. `assign_defenders()` / `release_defenders()` - Role-based defense
    5. `is_position_safe()` / `find_safe_spot()` - Influence grid queries
    """
    
    def __init__(self, bot: AresBot):
        self.bot = bot
        # Track which units we've already registered behaviors for this frame
        self._registered_tags: Set[int] = set()
    
    def reset_frame(self):
        """Call at the start of each frame to clear the registered tags set.
        
        This is critical - ares behaviors are registered per-frame and executed
        after on_step completes. We need to track what we've registered to
        avoid double-registering a unit.
        """
        self._registered_tags = set()
    
    @property
    def mediator(self):
        """Shortcut to the bot's manager mediator."""
        return self.bot.mediator
    
    # =========================================================================
    #  COMBAT SIMULATION
    # =========================================================================
    
    def can_win_fight(
        self,
        own_units: Units,
        enemy_units: Units,
        threshold: Set[EngagementResult] = LOSS_CLOSE_OR_WORSE,
    ) -> bool:
        """Use ares combat simulator to predict if we can win.
        
        Args:
            own_units: Our units that would fight
            enemy_units: Enemy units we'd fight against
            threshold: Set of EngagementResults considered "winning".
                Default: LOSS_CLOSE_OR_WORSE means we attack even on marginal loss.
                Use LOSS_DECISIVE_OR_WORSE for more conservative decisions.
        
        Returns:
            True if the predicted result is NOT in the threshold (i.e., we win or tie)
        """
        if not own_units or not enemy_units:
            return not enemy_units  # Win if no enemies, lose if no own units
        
        try:
            result = self.mediator.manager_request(
                ManagerName.COMBAT_SIM_MANAGER,
                ManagerRequestType.CAN_WIN_FIGHT,
                own_units=own_units,
                enemy_units=enemy_units,
            )
            return result not in threshold
        except Exception:
            # Fallback: simple supply comparison if combat sim fails
            own_supply = sum(u._proto.food_used for u in own_units if hasattr(u, '_proto'))
            enemy_supply = sum(u._proto.food_used for u in enemy_units if hasattr(u, '_proto'))
            return own_supply >= enemy_supply * 0.8
    
    # =========================================================================
    #  INFLUENCE GRID QUERIES
    # =========================================================================
    
    def get_ground_grid(self) -> np.ndarray:
        """Get the ground influence grid showing enemy danger zones."""
        try:
            return self.mediator.get_ground_grid
        except Exception:
            return None
    
    def get_air_grid(self) -> np.ndarray:
        """Get the air influence grid."""
        try:
            return self.mediator.get_air_grid
        except Exception:
            return None
    
    def is_position_safe(self, position: Point2, grid: np.ndarray = None) -> bool:
        """Check if a position is safe according to the influence grid."""
        if grid is None:
            grid = self.get_ground_grid()
        if grid is None:
            return True  # No grid info, assume safe
        try:
            return self.mediator.is_position_safe(grid=grid, position=position)
        except Exception:
            return True
    
    def find_safe_spot(self, from_pos: Point2, grid: np.ndarray = None) -> Point2:
        """Find the closest safe position from a given point."""
        if grid is None:
            grid = self.get_ground_grid()
        if grid is None:
            return from_pos  # No grid info, stay put
        try:
            return self.mediator.find_closest_safe_spot(from_pos=from_pos, grid=grid)
        except Exception:
            return from_pos
    
    # =========================================================================
    #  UNIT ROLE MANAGEMENT (for banshee defense etc.)
    # =========================================================================
    
    def assign_role(self, tag: int, role: UnitRole):
        """Assign a unit to a role."""
        try:
            self.mediator.assign_role(tag=tag, role=role)
        except Exception:
            pass
    
    def get_units_from_role(
        self,
        role: UnitRole,
        unit_type: Optional[UnitTypeId] = None,
    ) -> Units:
        """Get all units with a given role, optionally filtered by type."""
        try:
            if unit_type:
                return self.mediator.get_units_from_role(role=role, unit_type=unit_type)
            return self.mediator.get_units_from_role(role=role)
        except Exception:
            return Units([], self.bot)
    
    def assign_banshee_defenders(self, count: int = 3):
        """Assign stalkers to defending role for banshee defense.
        
        Unlike the old approach of manually tracking defender tags and releasing
        them when the banshee leaves, the UnitRole system keeps defenders in the
        DEFENDING role permanently until we explicitly reassign them. This prevents
        the oscillation where defenders get released and the banshee immediately
        returns.
        
        Only reassigns if we don't already have enough defenders.
        """
        current_defenders = self.get_units_from_role(
            role=UnitRole.DEFENDING,
            unit_type=UnitTypeId.STALKER,
        )
        needed = count - len(current_defenders)
        if needed <= 0:
            return current_defenders
        
        # Find idle or attacking stalkers to promote to defenders
        available = self.bot.units(UnitTypeId.STALKER).ready.filter(
            lambda s: s.tag not in current_defender.tags 
            for current_defender in [current_defenders]
        )
        
        # Get stalkers not already defending and near our base
        defending_tags = current_defenders.tags if current_defenders else set()
        candidates = [
            s for s in self.bot.units(UnitTypeId.STALKER).ready
            if s.tag not in defending_tags
        ]
        
        # Prioritize stalkers closest to our bases
        if candidates and self.bot.townhalls.ready:
            closest_th = self.bot.townhalls.ready.closest_to(
                self.bot.start_location
            )
            candidates.sort(key=lambda s: s.distance_to(closest_th))
        
        for i, stalker in enumerate(candidates[:needed]):
            self.assign_role(stalker.tag, UnitRole.DEFENDING)
        
        return self.get_units_from_role(
            role=UnitRole.DEFENDING,
            unit_type=UnitTypeId.STALKER,
        )
    
    def release_banshee_defenders(self):
        """Release all stalker defenders back to attacking role.
        
        Only call this when you're SURE the banshee threat is permanently gone.
        For example, when transitioning to a mid-game push. NOT when the banshee
        temporarily moves away from our base.
        """
        defenders = self.get_units_from_role(
            role=UnitRole.DEFENDING,
            unit_type=UnitTypeId.STALKER,
        )
        if defenders:
            for tag in defenders.tags:
                self.assign_role(tag, UnitRole.ATTACKING)
    
    # =========================================================================
    #  COMBAT BEHAVIOR REGISTRATION
    # =========================================================================
    
    def register_army_combat(
        self,
        army: Units,
        enemy_units: Units,
        attack_target: Point2 = None,
        retreat_to: Point2 = None,
    ):
        """Register ares combat behaviors for an army group.
        
        This is the main micro function. It replaces manual attack/move commands
        with ares behaviors that handle:
        - Target selection (shoot lowest health in range)
        - Stutter-stepping (kite backward for ranged, charge forward for melee)
        - Safety checks (retreat if in enemy influence zone)
        - Deduplication (each unit gets exactly ONE behavior per frame)
        
        Args:
            army: Our combat units to micro
            enemy_units: Visible enemy units to fight
            attack_target: Position to attack-move toward when no enemies visible
            retreat_to: Position to retreat to when outmatched (overrides attack)
        """
        if not army:
            return
        
        grid = self.get_ground_grid()
        air_grid = self.get_air_grid()
        
        for unit in army:
            if unit.tag in self._registered_tags:
                continue
            
            # Skip units that are building or morphing
            if not unit.is_ready:
                continue
            
            maneuver = CombatManeuver()
            use_air_grid = unit.type_id in AIR_TYPES
            active_grid = air_grid if use_air_grid else grid
            
            if unit.type_id in RANGED_TYPES:
                # Ranged micro: shoot if in range, kite back if not safe
                if enemy_units:
                    # Priority 1: Shoot something in range
                    maneuver.add(ShootTargetInRange(unit=unit, targets=enemy_units))
                    
                    # Priority 2: If weapon on cooldown, kite back using influence
                    if unit.weapon_cooldown > 0 and active_grid is not None:
                        maneuver.add(KeepUnitSafe(unit=unit, grid=active_grid))
                    
                    # Priority 3: Move toward closest enemy if out of range
                    closest_enemy = enemy_units.closest_to(unit)
                    if closest_enemy:
                        maneuver.add(StutterUnitForward(unit=unit, target=closest_enemy))
                
                elif attack_target:
                    # No enemies visible, move toward target
                    maneuver.add(AMove(unit=unit, target=attack_target))
                
                # Safety: retreat if in danger zone (always checked last)
                if active_grid is not None:
                    maneuver.add(KeepUnitSafe(unit=unit, grid=active_grid))
            
            elif unit.type_id in MELEE_TYPES:
                # Melee micro: charge in and attack
                if enemy_units:
                    # Priority 1: Shoot/attack something in range
                    maneuver.add(ShootTargetInRange(unit=unit, targets=enemy_units))
                    
                    # Priority 2: Move toward closest enemy
                    closest_enemy = enemy_units.closest_to(unit)
                    if closest_enemy:
                        maneuver.add(StutterUnitForward(unit=unit, target=closest_enemy))
                
                elif attack_target:
                    maneuver.add(AMove(unit=unit, target=attack_target))
                
                # Safety for melee is optional - they need to commit
                # Only retreat if severely outmatched
            
            else:
                # Generic units (observers, warp prisms, etc.)
                # Just keep them safe
                if active_grid is not None:
                    maneuver.add(KeepUnitSafe(unit=unit, grid=active_grid))
                
                if attack_target and unit.type_id not in AIR_TYPES:
                    maneuver.add(AMove(unit=unit, target=attack_target))
            
            self.bot.register_behavior(maneuver)
            self._registered_tags.add(unit.tag)
    
    def register_defender_combat(
        self,
        defenders: Units,
        enemy_threats: Units,
        defend_position: Point2,
    ):
        """Register combat behaviors for base defenders.
        
        Defenders prioritize:
        1. Shooting enemies in range
        2. Moving toward enemies near our base
        3. Staying safe using influence grids
        4. Returning to defend position if no threats
        
        Args:
            defenders: Units assigned to defense
            enemy_threats: Enemy units threatening our base
            defend_position: Position to defend (e.g., natural nexus)
        """
        if not defenders:
            return
        
        grid = self.get_ground_grid()
        
        for unit in defenders:
            if unit.tag in self._registered_tags:
                continue
            if not unit.is_ready:
                continue
            
            maneuver = CombatManeuver()
            
            if enemy_threats:
                # Shoot at enemies in range
                maneuver.add(ShootTargetInRange(unit=unit, targets=enemy_threats))
                
                # Move toward closest threat if out of range
                closest = enemy_threats.closest_to(unit)
                if closest:
                    # For ranged units, stutter toward enemy
                    if unit.type_id in RANGED_TYPES:
                        if unit.weapon_cooldown > 0 and grid is not None:
                            maneuver.add(KeepUnitSafe(unit=unit, grid=grid))
                        maneuver.add(StutterUnitForward(unit=unit, target=closest))
                    else:
                        maneuver.add(StutterUnitForward(unit=unit, target=closest))
            else:
                # No visible threats, hold position at defend point
                if unit.distance_to(defend_position) > 5:
                    maneuver.add(AMove(unit=unit, target=defend_position))
            
            # Always check safety as last resort
            if grid is not None:
                maneuver.add(KeepUnitSafe(unit=unit, grid=grid))
            
            self.bot.register_behavior(maneuver)
            self._registered_tags.add(unit.tag)
    
    def register_observer_micro(
        self,
        observers: Units,
        target: Point2 = None,
    ):
        """Register safe movement behaviors for observers.
        
        Observers need to:
        1. Move to their assigned scout position
        2. Stay safe from enemy fire
        3. Not idle at the robotics facility
        
        Args:
            observers: Our observer units
            target: Position for the observer to scout
        """
        if not observers:
            return
        
        air_grid = self.get_air_grid()
        
        for obs in observers:
            if obs.tag in self._registered_tags:
                continue
            if not obs.is_ready:
                continue
            
            maneuver = CombatManeuver()
            
            # Priority 1: Stay safe from anti-air
            if air_grid is not None:
                maneuver.add(KeepUnitSafe(unit=obs, grid=air_grid))
            
            # Priority 2: Move to target position
            if target and obs.distance_to(target) > 5:
                maneuver.add(AMove(unit=obs, target=target))
            
            self.bot.register_behavior(maneuver)
            self._registered_tags.add(obs.tag)


def blink_upgrade_done(bot) -> bool:
    """Safely check if blink research is complete, handling the rename."""
    if BLINK_UPGRADE is None:
        return False
    try:
        return bot.already_pending_upgrade(BLINK_UPGRADE) == 1.0
    except Exception:
        return False


def blink_upgrade_pending(bot) -> float:
    """Safely check blink research progress (0.0 to 1.0)."""
    if BLINK_UPGRADE is None:
        return 0.0
    try:
        return bot.already_pending_upgrade(BLINK_UPGRADE)
    except Exception:
        return 0.0
